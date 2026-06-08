"""
Fetch OpenAlex referenced_works for pending paper enrichment candidates.

The script is idempotent and resumable:
- pending/failed rows are claimed as in_progress in small batches.
- fetched rows are not fetched again unless --retry-failed is used for failed rows.
- reference/related edges are upserted by primary key.

Usage:
    cd backend
    .venv/bin/python -m scripts.enrich_openalex_references --limit 100 --concurrency 5
    .venv/bin/python -m scripts.enrich_openalex_references --limit 10000 --concurrency 5 --retry-failed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text

from app.db.database import AsyncSessionLocal


SOURCE = "openalex"
OPENALEX_WORK_URL = "https://api.openalex.org/works/{paper_id}"


CLAIM_SQL = text("""
WITH picked AS (
    SELECT paper_id
    FROM paper_enrichment_status
    WHERE source = :source
      AND (
          status = 'pending'
          OR (:retry_failed AND status = 'failed')
          OR (
              status = 'in_progress'
              AND last_attempted_at < now() - make_interval(mins => :stale_minutes)
          )
      )
      AND attempt_count < :max_attempts
    ORDER BY candidate_score DESC NULLS LAST, created_at ASC, paper_id
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
)
UPDATE paper_enrichment_status pes
SET status = 'in_progress',
    attempt_count = pes.attempt_count + 1,
    last_attempted_at = now(),
    updated_at = now(),
    error = NULL
FROM picked
WHERE pes.paper_id = picked.paper_id
  AND pes.source = :source
RETURNING pes.paper_id
""")

MATCH_TARGET_SQL = text("""
SELECT id
FROM papers
WHERE id = ANY(:ids)
""")

UPSERT_ENRICHMENT_SQL = text("""
INSERT INTO paper_openalex_enrichments (
    paper_id,
    openalex_id,
    publication_date,
    language,
    source_id,
    source_display_name,
    source_type,
    landing_page_url,
    pdf_url,
    best_oa_url,
    is_oa,
    ids,
    primary_location,
    best_oa_location,
    referenced_works_count,
    related_works_count,
    fetched_at
)
VALUES (
    :paper_id,
    :openalex_id,
    :publication_date,
    :language,
    :source_id,
    :source_display_name,
    :source_type,
    :landing_page_url,
    :pdf_url,
    :best_oa_url,
    :is_oa,
    CAST(:ids AS jsonb),
    CAST(:primary_location AS jsonb),
    CAST(:best_oa_location AS jsonb),
    :referenced_works_count,
    :related_works_count,
    now()
)
ON CONFLICT (paper_id) DO UPDATE SET
    openalex_id = EXCLUDED.openalex_id,
    publication_date = EXCLUDED.publication_date,
    language = EXCLUDED.language,
    source_id = EXCLUDED.source_id,
    source_display_name = EXCLUDED.source_display_name,
    source_type = EXCLUDED.source_type,
    landing_page_url = EXCLUDED.landing_page_url,
    pdf_url = EXCLUDED.pdf_url,
    best_oa_url = EXCLUDED.best_oa_url,
    is_oa = EXCLUDED.is_oa,
    ids = EXCLUDED.ids,
    primary_location = EXCLUDED.primary_location,
    best_oa_location = EXCLUDED.best_oa_location,
    referenced_works_count = EXCLUDED.referenced_works_count,
    related_works_count = EXCLUDED.related_works_count,
    fetched_at = now()
""")

UPSERT_REFERENCE_SQL = text("""
INSERT INTO paper_reference_edges (
    source_paper_id,
    target_openalex_id,
    target_paper_id,
    source,
    observed_at
)
VALUES (
    :source_paper_id,
    :target_openalex_id,
    :target_paper_id,
    :source,
    now()
)
ON CONFLICT (source_paper_id, target_openalex_id, source) DO UPDATE SET
    target_paper_id = EXCLUDED.target_paper_id,
    observed_at = now()
""")

UPSERT_RELATED_SQL = text("""
INSERT INTO paper_related_edges (
    source_paper_id,
    target_openalex_id,
    target_paper_id,
    rank,
    source,
    observed_at
)
VALUES (
    :source_paper_id,
    :target_openalex_id,
    :target_paper_id,
    :rank,
    :source,
    now()
)
ON CONFLICT (source_paper_id, target_openalex_id, source) DO UPDATE SET
    target_paper_id = EXCLUDED.target_paper_id,
    rank = EXCLUDED.rank,
    observed_at = now()
""")

MARK_FETCHED_SQL = text("""
UPDATE paper_enrichment_status
SET status = 'fetched',
    fetched_at = now(),
    updated_at = now(),
    error = NULL,
    referenced_works_count = :referenced_works_count,
    related_works_count = :related_works_count
WHERE paper_id = :paper_id
  AND source = :source
""")

MARK_FAILED_SQL = text("""
UPDATE paper_enrichment_status
SET status = 'failed',
    updated_at = now(),
    error = :error
WHERE paper_id = :paper_id
  AND source = :source
""")

SUMMARY_SQL = text("""
SELECT status, COUNT(*) AS n
FROM paper_enrichment_status
WHERE source = :source
GROUP BY status
ORDER BY status
""")

EDGE_SUMMARY_SQL = text("""
SELECT
    (SELECT COUNT(*) FROM paper_reference_edges WHERE source = :source) AS reference_edges,
    (SELECT COUNT(*) FROM paper_reference_edges WHERE source = :source AND target_paper_id IS NOT NULL) AS internal_reference_edges,
    (SELECT COUNT(*) FROM paper_related_edges WHERE source = :source) AS related_edges,
    (SELECT COUNT(*) FROM paper_openalex_enrichments) AS enrichment_rows
""")


@dataclass(slots=True)
class FetchResult:
    paper_id: str
    ok: bool
    work: dict[str, Any] | None = None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="Maximum papers to fetch this run.")
    parser.add_argument("--batch-size", type=int, default=50, help="DB claim batch size.")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--stale-minutes", type=int, default=120)
    parser.add_argument("--email", help="Optional email for OpenAlex polite pool.")
    parser.add_argument("--dry-run", action="store_true", help="Claim and fetch, but do not write enrichment results.")
    return parser.parse_args()


def openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/").split("/")[-1]


def ids_from_list(values: list[str] | None) -> list[str]:
    out = []
    for value in values or []:
        wid = openalex_id(value)
        if wid:
            out.append(wid)
    return out


async def claim_batch(args: argparse.Namespace, limit: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                CLAIM_SQL,
                {
                    "source": SOURCE,
                    "retry_failed": args.retry_failed,
                    "stale_minutes": args.stale_minutes,
                    "max_attempts": args.max_attempts,
                    "limit": limit,
                },
            )
        ).fetchall()
        await db.commit()
    return [row.paper_id for row in rows]


async def fetch_one(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, paper_id: str) -> FetchResult:
    async with semaphore:
        try:
            response = await client.get(OPENALEX_WORK_URL.format(paper_id=paper_id))
            response.raise_for_status()
            return FetchResult(paper_id=paper_id, ok=True, work=response.json())
        except Exception as exc:  # noqa: BLE001 - preserve failure reason for resumable jobs
            return FetchResult(paper_id=paper_id, ok=False, error=str(exc)[:1000])


async def internal_matches(ids: list[str]) -> set[str]:
    if not ids:
        return set()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(MATCH_TARGET_SQL, {"ids": ids})).fetchall()
    return {row.id for row in rows}


def enrichment_payload(paper_id: str, work: dict[str, Any]) -> dict[str, Any]:
    primary_location = work.get("primary_location") or {}
    best_oa_location = work.get("best_oa_location") or {}
    source = primary_location.get("source") or {}
    best_oa_url = best_oa_location.get("landing_page_url") or best_oa_location.get("pdf_url")
    return {
        "paper_id": paper_id,
        "openalex_id": openalex_id(work.get("id")) or paper_id,
        "publication_date": work.get("publication_date"),
        "language": work.get("language"),
        "source_id": openalex_id(source.get("id")),
        "source_display_name": source.get("display_name"),
        "source_type": source.get("type"),
        "landing_page_url": primary_location.get("landing_page_url"),
        "pdf_url": primary_location.get("pdf_url"),
        "best_oa_url": best_oa_url,
        "is_oa": bool((work.get("open_access") or {}).get("is_oa")),
        "ids": json.dumps(work.get("ids") or {}),
        "primary_location": json.dumps(primary_location),
        "best_oa_location": json.dumps(best_oa_location),
        "referenced_works_count": len(work.get("referenced_works") or []),
        "related_works_count": len(work.get("related_works") or []),
    }


async def persist_result(result: FetchResult, dry_run: bool) -> tuple[int, int]:
    if not result.ok or not result.work:
        async with AsyncSessionLocal() as db:
            await db.execute(
                MARK_FAILED_SQL,
                {
                    "paper_id": result.paper_id,
                    "source": SOURCE,
                    "error": result.error or "unknown error",
                },
            )
            await db.commit()
        return 0, 0

    refs = ids_from_list(result.work.get("referenced_works"))
    related = ids_from_list(result.work.get("related_works"))
    matched = await internal_matches(sorted(set(refs + related)))
    if dry_run:
        return len(refs), sum(1 for ref in refs if ref in matched)

    async with AsyncSessionLocal() as db:
        await db.execute(UPSERT_ENRICHMENT_SQL, enrichment_payload(result.paper_id, result.work))
        for target_id in refs:
            await db.execute(
                UPSERT_REFERENCE_SQL,
                {
                    "source_paper_id": result.paper_id,
                    "target_openalex_id": target_id,
                    "target_paper_id": target_id if target_id in matched else None,
                    "source": SOURCE,
                },
            )
        for rank, target_id in enumerate(related, start=1):
            await db.execute(
                UPSERT_RELATED_SQL,
                {
                    "source_paper_id": result.paper_id,
                    "target_openalex_id": target_id,
                    "target_paper_id": target_id if target_id in matched else None,
                    "rank": rank,
                    "source": SOURCE,
                },
            )
        await db.execute(
            MARK_FETCHED_SQL,
            {
                "paper_id": result.paper_id,
                "source": SOURCE,
                "referenced_works_count": len(refs),
                "related_works_count": len(related),
            },
        )
        await db.commit()
    return len(refs), sum(1 for ref in refs if ref in matched)


async def print_summary() -> None:
    async with AsyncSessionLocal() as db:
        status_rows = (await db.execute(SUMMARY_SQL, {"source": SOURCE})).fetchall()
        edge_row = (await db.execute(EDGE_SUMMARY_SQL, {"source": SOURCE})).one()
    print("\nStatus:")
    for row in status_rows:
        print(f"  {row.status}: {int(row.n):,}")
    print("Edges:")
    print(f"  reference_edges: {int(edge_row.reference_edges or 0):,}")
    print(f"  internal_reference_edges: {int(edge_row.internal_reference_edges or 0):,}")
    print(f"  related_edges: {int(edge_row.related_edges or 0):,}")
    print(f"  enrichment_rows: {int(edge_row.enrichment_rows or 0):,}")


async def main() -> None:
    args = parse_args()
    headers = {"User-Agent": "ResearcherHub reference enrichment"}
    params = {}
    if args.email:
        params["mailto"] = args.email

    processed = 0
    fetched = 0
    failed = 0
    total_refs = 0
    total_internal_refs = 0
    started = time.time()
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(headers=headers, params=params, timeout=args.timeout, follow_redirects=True) as client:
        while processed < args.limit:
            claim_size = min(args.batch_size, args.limit - processed)
            paper_ids = await claim_batch(args, claim_size)
            if not paper_ids:
                print("no pending candidates to fetch", flush=True)
                break

            print(f"claimed {len(paper_ids):,} papers", flush=True)
            results = await asyncio.gather(*(fetch_one(client, semaphore, paper_id) for paper_id in paper_ids))
            for result in results:
                processed += 1
                if result.ok:
                    fetched += 1
                else:
                    failed += 1
                ref_count, internal_ref_count = await persist_result(result, args.dry_run)
                total_refs += ref_count
                total_internal_refs += internal_ref_count
                if processed % 25 == 0 or processed == args.limit:
                    elapsed = max(time.time() - started, 0.001)
                    print(
                        f"processed={processed:,} fetched={fetched:,} failed={failed:,} "
                        f"refs={total_refs:,} internal_refs={total_internal_refs:,} "
                        f"rate={processed / elapsed:.2f}/s",
                        flush=True,
                    )

    print(
        f"\nDone. processed={processed:,}, fetched={fetched:,}, failed={failed:,}, "
        f"refs={total_refs:,}, internal_refs={total_internal_refs:,}",
        flush=True,
    )
    if total_refs:
        print(f"internal reference ratio: {total_internal_refs / total_refs * 100:.2f}%")
    await print_summary()


if __name__ == "__main__":
    asyncio.run(main())
