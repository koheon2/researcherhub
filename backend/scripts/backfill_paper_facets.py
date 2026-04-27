"""
Backfill weak paper facets from papers metadata.

Usage:
    cd backend
    .venv/bin/python -m scripts.backfill_paper_facets
    .venv/bin/python -m scripts.backfill_paper_facets --mode aboutness
"""

from __future__ import annotations

import argparse
import asyncio
import time

from sqlalchemy import text

from app.db.database import AsyncSessionLocal
from app.services.paper_facets import build_paper_facets


BATCH_SIZE = 10000


ABOUTNESS_SUBFIELD_SQL = text("""
INSERT INTO paper_facets (
    paper_id,
    facet_type,
    facet_value,
    source,
    confidence,
    rank
)
SELECT
    id AS paper_id,
    'aboutness' AS facet_type,
    subfield AS facet_value,
    'paper_subfield' AS source,
    0.9 AS confidence,
    1 AS rank
FROM papers
WHERE subfield IS NOT NULL
  AND subfield <> ''
ON CONFLICT ON CONSTRAINT uq_paper_facets_identity DO UPDATE
SET
    confidence = EXCLUDED.confidence,
    rank = EXCLUDED.rank
""")


ABOUTNESS_TOPIC_SQL = text("""
INSERT INTO paper_facets (
    paper_id,
    facet_type,
    facet_value,
    source,
    confidence,
    rank
)
SELECT
    id AS paper_id,
    'aboutness' AS facet_type,
    topic AS facet_value,
    'paper_topic' AS source,
    0.75 AS confidence,
    2 AS rank
FROM papers
WHERE topic IS NOT NULL
  AND topic <> ''
ON CONFLICT ON CONSTRAINT uq_paper_facets_identity DO UPDATE
SET
    confidence = EXCLUDED.confidence,
    rank = EXCLUDED.rank
""")

FETCH_SQL = text("""
SELECT id, title, abstract, subfield, topic
FROM papers
WHERE id > :last_id
  AND COALESCE(NULLIF(title, ''), NULLIF(abstract, '')) IS NOT NULL
ORDER BY id
LIMIT :limit
""")


FETCH_INITIAL_SQL = text("""
SELECT id, title, abstract, subfield, topic
FROM papers
WHERE COALESCE(NULLIF(title, ''), NULLIF(abstract, '')) IS NOT NULL
ORDER BY id
LIMIT :limit
""")


INSERT_SQL = text("""
INSERT INTO paper_facets (
    paper_id,
    facet_type,
    facet_value,
    source,
    confidence,
    rank
)
VALUES (
    :paper_id,
    :facet_type,
    :facet_value,
    :source,
    :confidence,
    :rank
)
ON CONFLICT ON CONSTRAINT uq_paper_facets_identity DO UPDATE
SET
    confidence = EXCLUDED.confidence,
    rank = EXCLUDED.rank
""")


COUNT_SQL = text("SELECT COUNT(*) FROM paper_facets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill weak paper facets from papers metadata.")
    parser.add_argument(
        "--mode",
        choices=("all", "aboutness", "keywords"),
        default="all",
        help="Run all facet backfills, only metadata aboutness facets, or only title/abstract keyword facets.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help="Keyword scan batch size. Ignored for --mode aboutness.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    total_insert_rows = 0
    last_id: str | None = None
    batch_count = 0
    t0 = time.time()

    async with AsyncSessionLocal() as db:
        before_count = int(await db.scalar(COUNT_SQL) or 0)
        print(f"target rows before:   {before_count:,}", flush=True)

        if args.mode in {"all", "aboutness"}:
            print("backfilling aboutness from papers.subfield...", flush=True)
            subfield_result = await db.execute(ABOUTNESS_SUBFIELD_SQL)
            await db.commit()
            subfield_rows = subfield_result.rowcount or 0
            print(f"subfield facet rows:  {subfield_rows:,}", flush=True)

            print("backfilling aboutness from papers.topic...", flush=True)
            topic_result = await db.execute(ABOUTNESS_TOPIC_SQL)
            await db.commit()
            topic_rows = topic_result.rowcount or 0
            print(f"topic facet rows:     {topic_rows:,}", flush=True)

            total_insert_rows += subfield_rows + topic_rows

        if args.mode == "aboutness":
            after_count = int(await db.scalar(COUNT_SQL) or 0)
            print("paper_facets aboutness backfill complete")
            print(f"processed facet rows: {total_insert_rows:,}")
            print(f"target rows after:    {after_count:,}")
            return

        while True:
            if last_id is None:
                result = await db.execute(FETCH_INITIAL_SQL, {"limit": args.batch_size})
            else:
                result = await db.execute(FETCH_SQL, {"last_id": last_id, "limit": args.batch_size})
            rows = result.fetchall()
            if not rows:
                break

            payload: list[dict] = []
            for row in rows:
                facets = build_paper_facets(
                    title=row.title,
                    abstract=row.abstract,
                    subfield=row.subfield,
                    topic=row.topic,
                )
                for facet_type, items in facets.items():
                    if facet_type == "aboutness":
                        continue
                    for item in items:
                        payload.append(
                            {
                                "paper_id": row.id,
                                "facet_type": facet_type,
                                "facet_value": item["facet_value"],
                                "source": item["source"],
                                "confidence": item["confidence"],
                                "rank": item["rank"],
                            }
                        )

            if payload:
                await db.execute(INSERT_SQL, payload)
                await db.commit()
                total_insert_rows += len(payload)

            last_id = rows[-1].id
            batch_count += 1
            if batch_count % 25 == 0:
                elapsed = time.time() - t0
                print(
                    f"processed keyword batches: {batch_count:,}, "
                    f"last_id={last_id}, facet rows seen={total_insert_rows:,}, "
                    f"elapsed={elapsed/60:.1f}m",
                    flush=True,
                )

        after_count = int(await db.scalar(COUNT_SQL) or 0)

    print("paper_facets backfill complete")
    print(f"processed facet rows: {total_insert_rows:,}")
    print(f"target rows after:    {after_count:,}")


if __name__ == "__main__":
    asyncio.run(main())
