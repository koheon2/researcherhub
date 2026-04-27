"""
Backfill publication-time institution name matches from local OpenAlex/ROR snapshots.

Usage:
    cd backend
    .venv/bin/python -m scripts.backfill_institution_name_matches
    .venv/bin/python -m scripts.backfill_institution_name_matches --limit 1000 --fuzzy-top 200
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


ROOT = Path(__file__).resolve().parent.parent
INST_DIR = ROOT / "data" / "institutions"
ROR_FILE = ROOT / "data" / "ror" / "v2.6-2026-04-14-ror-data.json"


@dataclass(frozen=True)
class InstitutionCandidate:
    canonical_name: str
    country_code: str
    institution_ror_id: str | None
    openalex_institution_id: str | None
    source: str
    normalized_name: str
    token_key: str


SOURCE_SQL = text("""
SELECT
    institution_name,
    country_code,
    COUNT(*)::bigint AS contributions
FROM paper_author_affiliations
WHERE institution_name IS NOT NULL
  AND institution_name <> ''
  AND country_code IS NOT NULL
  AND country_code <> ''
GROUP BY institution_name, country_code
ORDER BY COUNT(*) DESC
LIMIT :limit
""")

UPSERT_SQL = text("""
INSERT INTO institution_name_matches (
    raw_institution_name,
    country_code,
    canonical_name,
    institution_ror_id,
    openalex_institution_id,
    match_source,
    confidence,
    status,
    observed_at
)
VALUES (
    :raw_institution_name,
    :country_code,
    :canonical_name,
    :institution_ror_id,
    :openalex_institution_id,
    :match_source,
    :confidence,
    :status,
    now()
)
ON CONFLICT ON CONSTRAINT uq_institution_name_matches_identity DO UPDATE
SET canonical_name = EXCLUDED.canonical_name,
    institution_ror_id = EXCLUDED.institution_ror_id,
    openalex_institution_id = EXCLUDED.openalex_institution_id,
    match_source = EXCLUDED.match_source,
    confidence = EXCLUDED.confidence,
    status = EXCLUDED.status
""")

COUNT_SQL = text("""
SELECT status, match_source, COUNT(*) AS n
FROM institution_name_matches
GROUP BY status, match_source
ORDER BY status, match_source
""")


def normalize_name(value: str | None) -> str:
    text_value = (value or "").lower()
    text_value = re.sub(r"\([^)]*\)", " ", text_value)
    text_value = text_value.replace("&", " and ")
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def token_key(normalized: str) -> str:
    tokens = normalized.split()
    if not tokens:
        return ""
    return tokens[0][:8]


def short_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/").split("/")[-1]


def ror_country(org: dict) -> str | None:
    locations = org.get("locations") or []
    if not locations:
        return None
    details = locations[0].get("geonames_details") or {}
    return details.get("country_code")


def ror_display_name(org: dict) -> str | None:
    names = org.get("names") or []
    for wanted in ("ror_display", "label"):
        for item in names:
            if wanted in (item.get("types") or []) and item.get("value"):
                return item["value"]
    if names:
        return names[0].get("value")
    return None


def ror_names(org: dict) -> list[str]:
    names: list[str] = []
    for item in org.get("names") or []:
        value = item.get("value")
        if value:
            names.append(value)
    return names


def add_candidate(
    index: dict[tuple[str, str], list[InstitutionCandidate]],
    by_country_token: dict[tuple[str, str], list[InstitutionCandidate]],
    candidate: InstitutionCandidate,
) -> None:
    if not candidate.normalized_name:
        return
    index[(candidate.normalized_name, candidate.country_code)].append(candidate)
    by_country_token[(candidate.country_code, candidate.token_key)].append(candidate)


def build_reference_indexes() -> tuple[
    dict[tuple[str, str], list[InstitutionCandidate]],
    dict[tuple[str, str], list[InstitutionCandidate]],
    dict[tuple[str, str], list[InstitutionCandidate]],
    dict[tuple[str, str], list[InstitutionCandidate]],
]:
    openalex_exact: dict[tuple[str, str], list[InstitutionCandidate]] = defaultdict(list)
    openalex_token: dict[tuple[str, str], list[InstitutionCandidate]] = defaultdict(list)
    ror_exact: dict[tuple[str, str], list[InstitutionCandidate]] = defaultdict(list)
    ror_token: dict[tuple[str, str], list[InstitutionCandidate]] = defaultdict(list)

    gz_files = sorted(INST_DIR.rglob("*.gz"))
    for gz_path in gz_files:
        with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    inst = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = inst.get("display_name")
                country = inst.get("country_code")
                normalized = normalize_name(name)
                if not name or not country or not normalized:
                    continue
                candidate = InstitutionCandidate(
                    canonical_name=name,
                    country_code=country,
                    institution_ror_id=short_id(inst.get("ror")),
                    openalex_institution_id=short_id(inst.get("id")),
                    source="openalex_display_name_exact",
                    normalized_name=normalized,
                    token_key=token_key(normalized),
                )
                add_candidate(openalex_exact, openalex_token, candidate)

    data = json.loads(ROR_FILE.read_text())
    for org in data:
        country = ror_country(org)
        canonical_name = ror_display_name(org)
        ror_id = short_id(org.get("id"))
        if not country or not canonical_name or not ror_id:
            continue
        for name in ror_names(org):
            normalized = normalize_name(name)
            if not normalized:
                continue
            candidate = InstitutionCandidate(
                canonical_name=canonical_name,
                country_code=country,
                institution_ror_id=ror_id,
                openalex_institution_id=None,
                source="ror_name_alias_exact",
                normalized_name=normalized,
                token_key=token_key(normalized),
            )
            add_candidate(ror_exact, ror_token, candidate)

    return openalex_exact, openalex_token, ror_exact, ror_token


def choose_exact(candidates: list[InstitutionCandidate]) -> InstitutionCandidate | None:
    if not candidates:
        return None
    identities = {
        (item.canonical_name, item.institution_ror_id, item.openalex_institution_id)
        for item in candidates
    }
    if len(identities) == 1:
        return candidates[0]
    return None


def match_one(
    raw_name: str,
    country_code: str,
    rank: int,
    fuzzy_top: int,
    openalex_exact: dict[tuple[str, str], list[InstitutionCandidate]],
    openalex_token: dict[tuple[str, str], list[InstitutionCandidate]],
    ror_exact: dict[tuple[str, str], list[InstitutionCandidate]],
    ror_token: dict[tuple[str, str], list[InstitutionCandidate]],
) -> dict:
    normalized = normalize_name(raw_name)
    key = (normalized, country_code)

    match = choose_exact(openalex_exact.get(key, []))
    if match:
        return row(raw_name, country_code, match, "openalex_display_name_exact", 0.98, "matched")

    if openalex_exact.get(key):
        return row(raw_name, country_code, None, "openalex_display_name_exact", 0.5, "ambiguous")

    match = choose_exact(ror_exact.get(key, []))
    if match:
        return row(raw_name, country_code, match, "ror_name_alias_exact", 0.95, "matched")

    if ror_exact.get(key):
        return row(raw_name, country_code, None, "ror_name_alias_exact", 0.5, "ambiguous")

    if rank <= fuzzy_top:
        candidates = openalex_token.get((country_code, token_key(normalized)), [])
        fuzzy = choose_fuzzy(normalized, candidates)
        if fuzzy:
            match, score = fuzzy
            return row(raw_name, country_code, match, "openalex_display_name_fuzzy", score, "matched")

    return row(raw_name, country_code, None, "no_local_snapshot_match", 0.0, "unmatched")


def choose_fuzzy(
    normalized: str,
    candidates: list[InstitutionCandidate],
) -> tuple[InstitutionCandidate, float] | None:
    if not normalized or not candidates:
        return None
    scored = sorted(
        (
            (SequenceMatcher(None, normalized, candidate.normalized_name).ratio(), candidate)
            for candidate in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.94 and best_score - second_score >= 0.04:
        return best, round(best_score, 4)
    return None


def row(
    raw_name: str,
    country_code: str,
    match: InstitutionCandidate | None,
    source: str,
    confidence: float,
    status: str,
) -> dict:
    return {
        "raw_institution_name": raw_name,
        "country_code": country_code,
        "canonical_name": match.canonical_name if match else None,
        "institution_ror_id": match.institution_ror_id if match else None,
        "openalex_institution_id": match.openalex_institution_id if match else None,
        "match_source": source,
        "confidence": confidence,
        "status": status,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit distinct institution/country pairs.")
    parser.add_argument(
        "--fuzzy-top",
        type=int,
        default=5000,
        help="Apply conservative fuzzy matching only to the top N unmatched pairs by contribution count.",
    )
    parser.add_argument("--batch-size", type=int, default=2000)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not INST_DIR.exists():
        raise SystemExit(f"OpenAlex institutions snapshot not found: {INST_DIR}")
    if not ROR_FILE.exists():
        raise SystemExit(f"ROR dump not found: {ROR_FILE}")

    print("building local institution indexes...", flush=True)
    openalex_exact, openalex_token, ror_exact, ror_token = build_reference_indexes()
    print(
        "indexes built: "
        f"openalex_exact={len(openalex_exact):,}, ror_exact={len(ror_exact):,}",
        flush=True,
    )

    async with AsyncSessionLocal() as db:
        source_rows = (
            await db.execute(SOURCE_SQL, {"limit": args.limit or 2_147_483_647})
        ).fetchall()

        batch: list[dict] = []
        status_counts: dict[str, int] = defaultdict(int)
        for rank, item in enumerate(source_rows, start=1):
            match = match_one(
                item.institution_name,
                item.country_code,
                rank,
                args.fuzzy_top,
                openalex_exact,
                openalex_token,
                ror_exact,
                ror_token,
            )
            status_counts[match["status"]] += 1
            batch.append(match)
            if len(batch) >= args.batch_size:
                await db.execute(UPSERT_SQL, batch)
                await db.commit()
                print(f"processed {rank:,}/{len(source_rows):,}", flush=True)
                batch.clear()

        if batch:
            await db.execute(UPSERT_SQL, batch)
            await db.commit()

        distribution = (await db.execute(COUNT_SQL)).fetchall()

    print("\ninstitution name match backfill complete")
    print(f"source pairs processed: {len(source_rows):,}")
    for status, count in sorted(status_counts.items()):
        print(f"{status}: {count:,}")
    print("\ncurrent match table distribution")
    for item in distribution:
        print(f"  {item.status} / {item.match_source}: {int(item.n):,}")


if __name__ == "__main__":
    asyncio.run(main())
