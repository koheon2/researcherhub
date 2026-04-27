"""
Backfill publication-time author affiliation rows from existing papers/paper_authors.

Usage:
    cd backend
    .venv/bin/python -m scripts.backfill_paper_author_affiliations
"""

import asyncio
from sqlalchemy import text

from app.db.database import AsyncSessionLocal


BACKFILL_SQL = text("""
INSERT INTO paper_author_affiliations (
    paper_id,
    author_id,
    author_name,
    position,
    institution_name,
    institution_ror_id,
    raw_affiliation,
    country_code,
    publication_year,
    source,
    confidence
)
SELECT
    pa.paper_id,
    pa.author_id,
    pa.author_name,
    COALESCE(pa.position, 0) AS position,
    NULLIF(pa.institution_name, '') AS institution_name,
    NULL AS institution_ror_id,
    NULLIF(pa.institution_name, '') AS raw_affiliation,
    UPPER(NULLIF(pa.country, '')) AS country_code,
    p.year AS publication_year,
    'existing_paper_authors' AS source,
    0.6 AS confidence
FROM paper_authors pa
JOIN papers p ON p.id = pa.paper_id
WHERE pa.paper_id IS NOT NULL
  AND pa.author_id IS NOT NULL
  AND pa.institution_name IS NOT NULL
  AND pa.institution_name <> ''
  AND pa.country IS NOT NULL
  AND pa.country <> ''
ON CONFLICT ON CONSTRAINT uq_paper_author_affiliation_source DO NOTHING
""")


COUNT_SOURCE_SQL = text("""
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


COUNT_TARGET_SQL = text("SELECT COUNT(*) FROM paper_author_affiliations")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        source_count = await db.scalar(COUNT_SOURCE_SQL)
        before_count = await db.scalar(COUNT_TARGET_SQL)
        result = await db.execute(BACKFILL_SQL)
        await db.commit()
        after_count = await db.scalar(COUNT_TARGET_SQL)

    inserted = result.rowcount if result.rowcount is not None else (after_count or 0) - (before_count or 0)
    print("paper_author_affiliations backfill complete")
    print(f"eligible source rows: {source_count or 0:,}")
    print(f"target rows before:   {before_count or 0:,}")
    print(f"inserted rows:        {inserted:,}")
    print(f"target rows after:    {after_count or 0:,}")


if __name__ == "__main__":
    asyncio.run(main())
