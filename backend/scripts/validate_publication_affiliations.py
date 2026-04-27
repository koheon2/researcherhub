"""
Validate publication-time author affiliation backfill quality.

Usage:
    cd backend
    .venv/bin/python -m scripts.validate_publication_affiliations
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


SOURCE = "existing_paper_authors"
MAX_MISSING_YEAR_RATIO = 0.01


ELIGIBLE_SOURCE_SQL = text("""
SELECT COUNT(*)
FROM paper_authors pa
JOIN papers p ON p.id = pa.paper_id
WHERE pa.paper_id IS NOT NULL
  AND pa.author_id IS NOT NULL
  AND pa.institution_name IS NOT NULL
  AND pa.institution_name <> ''
  AND pa.country IS NOT NULL
  AND pa.country <> ''
""")


TARGET_SOURCE_SQL = text("""
SELECT COUNT(*)
FROM paper_author_affiliations
WHERE source = :source
""")


DUPLICATE_SQL = text("""
SELECT COUNT(*)
FROM (
    SELECT
        paper_id,
        author_id,
        position,
        institution_name,
        country_code,
        source,
        COUNT(*) AS n
    FROM paper_author_affiliations
    GROUP BY
        paper_id,
        author_id,
        position,
        institution_name,
        country_code,
        source
    HAVING COUNT(*) > 1
) dupes
""")


NULL_QUALITY_SQL = text("""
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN country_code IS NULL OR country_code = '' THEN 1 ELSE 0 END) AS missing_country,
    SUM(CASE WHEN institution_name IS NULL OR institution_name = '' THEN 1 ELSE 0 END) AS missing_institution,
    SUM(CASE WHEN publication_year IS NULL THEN 1 ELSE 0 END) AS missing_year,
    MIN(publication_year) AS min_year,
    MAX(publication_year) AS max_year
FROM paper_author_affiliations
WHERE source = :source
""")


TOP_COUNTRIES_SQL = text("""
SELECT
    country_code,
    COUNT(*) AS contributions,
    COUNT(DISTINCT paper_id) AS papers,
    ROUND(AVG(p.citations)::numeric, 2) AS avg_paper_citations
FROM paper_author_affiliations paa
JOIN papers p ON p.id = paa.paper_id
WHERE paa.source = :source
GROUP BY country_code
ORDER BY contributions DESC
LIMIT 10
""")


TOP_INSTITUTIONS_SQL = text("""
SELECT
    institution_name,
    COUNT(*) AS contributions,
    COUNT(DISTINCT paper_id) AS papers,
    ROUND(AVG(p.citations)::numeric, 2) AS avg_paper_citations
FROM paper_author_affiliations paa
JOIN papers p ON p.id = paa.paper_id
WHERE paa.source = :source
GROUP BY institution_name
ORDER BY contributions DESC
LIMIT 10
""")


COUNTRY_SUMMARY_SQL = text("""
SELECT
    paa.country_code,
    COUNT(*) AS contributions,
    COUNT(DISTINCT paa.paper_id) AS papers,
    COALESCE(SUM(p.citations), 0) AS total_citations,
    ROUND(AVG(p.citations)::numeric, 2) AS avg_paper_citations,
    MIN(paa.publication_year) AS min_year,
    MAX(paa.publication_year) AS max_year
FROM paper_author_affiliations paa
JOIN papers p ON p.id = paa.paper_id
WHERE paa.source = :source
  AND paa.country_code IN ('US', 'KR')
GROUP BY paa.country_code
ORDER BY paa.country_code
""")


def _pct(part: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{(part / total) * 100:.2f}%"


def _ratio(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return part / total


def _print_rows(title: str, rows: Sequence, name_field: str) -> None:
    print(f"\n{title}")
    if not rows:
        print("  none")
        return
    for row in rows:
        data = row._mapping
        print(
            "  "
            f"{data[name_field]}: "
            f"{int(data['contributions'] or 0):,} contributions, "
            f"{int(data['papers'] or 0):,} papers, "
            f"{float(data['avg_paper_citations'] or 0):.2f} avg paper citations"
        )


async def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    async with AsyncSessionLocal() as db:
        eligible_source = int(await db.scalar(ELIGIBLE_SOURCE_SQL) or 0)
        target_source = int(
            await db.scalar(TARGET_SOURCE_SQL, {"source": SOURCE}) or 0
        )
        duplicate_groups = int(await db.scalar(DUPLICATE_SQL) or 0)

        quality_result = await db.execute(NULL_QUALITY_SQL, {"source": SOURCE})
        quality = quality_result.one()._mapping
        total_rows = int(quality["total_rows"] or 0)
        missing_country = int(quality["missing_country"] or 0)
        missing_institution = int(quality["missing_institution"] or 0)
        missing_year = int(quality["missing_year"] or 0)

        top_country_result = await db.execute(TOP_COUNTRIES_SQL, {"source": SOURCE})
        top_countries = top_country_result.fetchall()

        top_institution_result = await db.execute(
            TOP_INSTITUTIONS_SQL, {"source": SOURCE}
        )
        top_institutions = top_institution_result.fetchall()

        summary_result = await db.execute(COUNTRY_SUMMARY_SQL, {"source": SOURCE})
        country_summary = summary_result.fetchall()

    if eligible_source != target_source:
        failures.append(
            "eligible paper_authors count does not match "
            "paper_author_affiliations source count"
        )
    if duplicate_groups > 0:
        failures.append("duplicate unique-key groups exist")
    if missing_country > 0:
        failures.append("blank country_code rows exist")
    if missing_institution > 0:
        failures.append("blank institution_name rows exist")
    missing_year_ratio = _ratio(missing_year, total_rows)
    if missing_year_ratio > MAX_MISSING_YEAR_RATIO:
        failures.append(
            "blank publication_year rows exceed "
            f"{MAX_MISSING_YEAR_RATIO:.0%} threshold"
        )
    elif missing_year > 0:
        warnings.append("blank publication_year rows exist below failure threshold")

    print("Publication-time affiliation validation")
    print(f"source: {SOURCE}")
    print(f"eligible paper_authors rows:       {eligible_source:,}")
    print(f"paper_author_affiliations rows:   {target_source:,}")
    print(f"duplicate unique-key groups:      {duplicate_groups:,}")
    print(
        "country_code missing:             "
        f"{missing_country:,} / {total_rows:,} ({_pct(missing_country, total_rows)})"
    )
    print(
        "institution_name missing:         "
        f"{missing_institution:,} / {total_rows:,} "
        f"({_pct(missing_institution, total_rows)})"
    )
    print(
        "publication_year missing:         "
        f"{missing_year:,} / {total_rows:,} ({_pct(missing_year, total_rows)})"
    )
    print(f"publication_year range:           {quality['min_year']} - {quality['max_year']}")

    _print_rows("Top countries", top_countries, "country_code")
    _print_rows("Top institutions", top_institutions, "institution_name")

    print("\nUS/KR summary")
    if not country_summary:
        print("  none")
    for row in country_summary:
        data = row._mapping
        print(
            "  "
            f"{data['country_code']}: "
            f"{int(data['contributions'] or 0):,} contributions, "
            f"{int(data['papers'] or 0):,} papers, "
            f"{int(data['total_citations'] or 0):,} total citations, "
            f"{float(data['avg_paper_citations'] or 0):.2f} avg paper citations, "
            f"{data['min_year']}-{data['max_year']}"
        )

    if failures:
        print("\nValidation failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    if warnings:
        print("\nValidation warnings")
        for warning in warnings:
            print(f"  - {warning}")

    print("\nValidation passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
