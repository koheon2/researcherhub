"""
Validate publication-time institution normalization coverage.

Usage:
    cd backend
    .venv/bin/python -m scripts.validate_institution_matches
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


SUMMARY_SQL = text("""
WITH source AS (
    SELECT institution_name, country_code, COUNT(*)::bigint AS contributions
    FROM paper_author_affiliations
    WHERE institution_name IS NOT NULL
      AND institution_name <> ''
      AND country_code IS NOT NULL
      AND country_code <> ''
    GROUP BY institution_name, country_code
),
joined AS (
    SELECT
        source.contributions,
        inm.status,
        inm.institution_ror_id
    FROM source
    LEFT JOIN institution_name_matches inm
      ON inm.raw_institution_name = source.institution_name
     AND inm.country_code = source.country_code
)
SELECT
    COUNT(*)::bigint AS distinct_pairs,
    COALESCE(SUM(contributions), 0)::bigint AS affiliation_rows,
    COUNT(*) FILTER (WHERE status = 'matched')::bigint AS matched_pairs,
    COALESCE(SUM(contributions) FILTER (WHERE status = 'matched'), 0)::bigint AS matched_rows,
    COUNT(*) FILTER (WHERE status = 'ambiguous')::bigint AS ambiguous_pairs,
    COUNT(*) FILTER (WHERE status = 'unmatched')::bigint AS unmatched_pairs,
    COUNT(*) FILTER (WHERE institution_ror_id IS NOT NULL AND institution_ror_id <> '')::bigint AS ror_pairs,
    COALESCE(SUM(contributions) FILTER (
        WHERE institution_ror_id IS NOT NULL AND institution_ror_id <> ''
    ), 0)::bigint AS ror_rows
FROM joined
""")

DISTRIBUTION_SQL = text("""
SELECT status, match_source, COUNT(*) AS n
FROM institution_name_matches
GROUP BY status, match_source
ORDER BY status, match_source
""")

TOP_UNMATCHED_SQL = text("""
SELECT
    source.institution_name,
    source.country_code,
    source.contributions,
    COALESCE(inm.status, '<missing>') AS status
FROM (
    SELECT institution_name, country_code, COUNT(*)::bigint AS contributions
    FROM paper_author_affiliations
    GROUP BY institution_name, country_code
) source
LEFT JOIN institution_name_matches inm
  ON inm.raw_institution_name = source.institution_name
 AND inm.country_code = source.country_code
WHERE COALESCE(inm.status, '<missing>') IN ('ambiguous', 'unmatched', '<missing>')
ORDER BY source.contributions DESC
LIMIT 20
""")

SMOKE_SQL = text("""
SELECT raw_institution_name, country_code, canonical_name, institution_ror_id, status, confidence
FROM institution_name_matches
WHERE lower(raw_institution_name) IN (
    'massachusetts institute of technology',
    'stanford university',
    'korea advanced institute of science and technology',
    'seoul national university'
)
ORDER BY raw_institution_name, country_code
""")

DUPLICATE_SQL = text("""
SELECT COUNT(*) FROM (
    SELECT raw_institution_name, country_code, COUNT(*)
    FROM institution_name_matches
    GROUP BY raw_institution_name, country_code
    HAVING COUNT(*) > 1
) duplicates
""")


def pct(part: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{part / total * 100:.2f}%"


async def main() -> int:
    async with AsyncSessionLocal() as db:
        summary = (await db.execute(SUMMARY_SQL)).one()._mapping
        distribution = (await db.execute(DISTRIBUTION_SQL)).fetchall()
        top_unmatched = (await db.execute(TOP_UNMATCHED_SQL)).fetchall()
        smoke = (await db.execute(SMOKE_SQL)).fetchall()
        duplicate_count = int(await db.scalar(DUPLICATE_SQL) or 0)

    distinct_pairs = int(summary["distinct_pairs"] or 0)
    affiliation_rows = int(summary["affiliation_rows"] or 0)
    matched_pairs = int(summary["matched_pairs"] or 0)
    matched_rows = int(summary["matched_rows"] or 0)
    ror_pairs = int(summary["ror_pairs"] or 0)
    ror_rows = int(summary["ror_rows"] or 0)

    print("Institution match validation")
    print(f"distinct institution/country pairs: {distinct_pairs:,}")
    print(f"affiliation rows:                   {affiliation_rows:,}")
    print(f"matched pairs:                      {matched_pairs:,} ({pct(matched_pairs, distinct_pairs)})")
    print(f"matched affiliation rows:           {matched_rows:,} ({pct(matched_rows, affiliation_rows)})")
    print(f"pairs with ROR:                     {ror_pairs:,} ({pct(ror_pairs, distinct_pairs)})")
    print(f"affiliation rows with ROR match:    {ror_rows:,} ({pct(ror_rows, affiliation_rows)})")
    print(f"duplicate match keys:               {duplicate_count:,}")

    print("\nMatch distribution")
    for row in distribution:
        print(f"  {row.status} / {row.match_source}: {int(row.n):,}")

    print("\nSmoke institutions")
    if not smoke:
        print("  none")
    for row in smoke:
        print(
            "  "
            f"{row.raw_institution_name} [{row.country_code}] -> "
            f"{row.canonical_name} / {row.institution_ror_id} "
            f"({row.status}, {float(row.confidence or 0):.2f})"
        )

    print("\nTop unmatched or ambiguous")
    for row in top_unmatched:
        print(
            "  "
            f"{row.institution_name} [{row.country_code}]: "
            f"{int(row.contributions):,} ({row.status})"
        )

    failures: list[str] = []
    if duplicate_count:
        failures.append("duplicate institution match keys exist")
    if matched_rows <= 0:
        failures.append("no affiliation rows matched")
    if ror_rows <= 0:
        failures.append("no affiliation rows have ROR matches")

    if failures:
        print("\nInstitution match validation failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nInstitution match validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
