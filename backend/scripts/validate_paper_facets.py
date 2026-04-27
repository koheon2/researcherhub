"""
Validate weak paper facets.

Usage:
    cd backend
    .venv/bin/python -m scripts.validate_paper_facets
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


TOTAL_SQL = text("SELECT COUNT(*) FROM paper_facets")

ABOUTNESS_ELIGIBLE_SQL = text("""
SELECT COUNT(*)
FROM papers
WHERE COALESCE(NULLIF(subfield, ''), NULLIF(topic, '')) IS NOT NULL
""")

ABOUTNESS_ACTUAL_SQL = text("""
SELECT COUNT(DISTINCT paper_id)
FROM paper_facets
WHERE facet_type = 'aboutness'
""")

DUPLICATE_SQL = text("""
SELECT COUNT(*)
FROM (
    SELECT
        paper_id,
        facet_type,
        facet_value,
        source,
        COUNT(*) AS n
    FROM paper_facets
    GROUP BY paper_id, facet_type, facet_value, source
    HAVING COUNT(*) > 1
) dupes
""")

TYPE_COUNTS_SQL = text("""
SELECT facet_type, COUNT(*) AS row_count, COUNT(DISTINCT paper_id) AS paper_count
FROM paper_facets
GROUP BY facet_type
ORDER BY facet_type
""")

TOP_VALUES_SQL = text("""
WITH ranked AS (
    SELECT
        facet_type,
        facet_value,
        COUNT(*) AS n,
        ROW_NUMBER() OVER (
            PARTITION BY facet_type
            ORDER BY COUNT(*) DESC, facet_value
        ) AS rn
    FROM paper_facets
    GROUP BY facet_type, facet_value
)
SELECT facet_type, facet_value, n
FROM ranked
WHERE rn <= 5
ORDER BY facet_type, n DESC, facet_value
""")


def _print_rows(title: str, rows: Sequence) -> None:
    print(f"\n{title}")
    if not rows:
        print("  none")
        return
    for row in rows:
        data = row._mapping
        if "paper_count" in data:
            print(
                f"  {data['facet_type']}: {int(data['row_count'] or 0):,} rows, "
                f"{int(data['paper_count'] or 0):,} papers"
            )
        else:
            print(f"  {data['facet_type']} / {data['facet_value']}: {int(data['n'] or 0):,}")


async def main() -> int:
    failures: list[str] = []
    async with AsyncSessionLocal() as db:
        total_rows = int(await db.scalar(TOTAL_SQL) or 0)
        eligible_aboutness = int(await db.scalar(ABOUTNESS_ELIGIBLE_SQL) or 0)
        actual_aboutness = int(await db.scalar(ABOUTNESS_ACTUAL_SQL) or 0)
        duplicates = int(await db.scalar(DUPLICATE_SQL) or 0)
        type_counts = (await db.execute(TYPE_COUNTS_SQL)).fetchall()
        top_values = (await db.execute(TOP_VALUES_SQL)).fetchall()

    if duplicates > 0:
        failures.append("duplicate paper facet identities exist")
    if actual_aboutness < eligible_aboutness:
        failures.append("aboutness facets are missing for papers with subfield/topic")

    print("Paper facet validation")
    print(f"paper_facets rows:              {total_rows:,}")
    print(f"eligible aboutness papers:      {eligible_aboutness:,}")
    print(f"actual aboutness papers:        {actual_aboutness:,}")
    print(f"duplicate identity groups:      {duplicates:,}")
    _print_rows("Facet type counts", type_counts)

    _print_rows("Top facet values", top_values)

    if failures:
        print("\nValidation failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nValidation passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
