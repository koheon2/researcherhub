"""
Refresh API summary tables from publication-time paper data.

Usage:
    cd backend
    .venv/bin/python -m scripts.refresh_publication_summaries
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


COUNTRY_SQL = text("""
INSERT INTO publication_country_stats (
    country_code,
    contributions,
    papers,
    total_citations,
    avg_paper_citations,
    top_field,
    min_year,
    max_year,
    refreshed_at
)
WITH stats AS (
    SELECT
        paa.country_code,
        COUNT(*)::bigint AS contributions,
        COUNT(DISTINCT paa.paper_id)::bigint AS papers,
        COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
        COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
        MIN(paa.publication_year) AS min_year,
        MAX(paa.publication_year) AS max_year
    FROM paper_author_affiliations paa
    JOIN papers p ON p.id = paa.paper_id
    WHERE paa.country_code IS NOT NULL
      AND paa.country_code <> ''
    GROUP BY paa.country_code
)
SELECT
    stats.country_code,
    stats.contributions,
    stats.papers,
    stats.total_citations,
    stats.avg_paper_citations,
    NULL AS top_field,
    stats.min_year,
    stats.max_year,
    now()
FROM stats
""")


INSTITUTION_SQL = text("""
INSERT INTO publication_institution_stats (
    institution_name,
    contributions,
    papers,
    total_citations,
    avg_paper_citations,
    top_field,
    min_year,
    max_year,
    refreshed_at
)
WITH stats AS (
    SELECT
        paa.institution_name,
        COUNT(*)::bigint AS contributions,
        COUNT(DISTINCT paa.paper_id)::bigint AS papers,
        COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
        COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
        MIN(paa.publication_year) AS min_year,
        MAX(paa.publication_year) AS max_year
    FROM paper_author_affiliations paa
    JOIN papers p ON p.id = paa.paper_id
    WHERE paa.institution_name IS NOT NULL
      AND paa.institution_name <> ''
    GROUP BY paa.institution_name
)
SELECT
    stats.institution_name,
    stats.contributions,
    stats.papers,
    stats.total_citations,
    stats.avg_paper_citations,
    NULL AS top_field,
    stats.min_year,
    stats.max_year,
    now()
FROM stats
""")


FACET_SQL = text("""
INSERT INTO paper_facet_summary (
    facet_type,
    facet_value,
    paper_count,
    total_citations,
    recent_papers,
    previous_papers,
    growth_pct,
    refreshed_at
)
WITH max_year AS (
    SELECT MAX(year) AS y
    FROM papers
    WHERE year IS NOT NULL
      AND year <= 2026
),
stats AS (
    SELECT
        pf.facet_type,
        pf.facet_value,
        COUNT(DISTINCT pf.paper_id)::bigint AS paper_count,
        COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
        COUNT(DISTINCT pf.paper_id) FILTER (WHERE p.year >= (SELECT y - 2 FROM max_year))::bigint AS recent_papers,
        COUNT(DISTINCT pf.paper_id) FILTER (
            WHERE p.year >= (SELECT y - 5 FROM max_year)
              AND p.year <= (SELECT y - 3 FROM max_year)
        )::bigint AS previous_papers
    FROM paper_facets pf
    JOIN papers p ON p.id = pf.paper_id
    GROUP BY pf.facet_type, pf.facet_value
)
SELECT
    facet_type,
    facet_value,
    paper_count,
    total_citations,
    recent_papers,
    previous_papers,
    CASE
        WHEN previous_papers > 0 THEN ((recent_papers - previous_papers)::float / previous_papers) * 100
        WHEN recent_papers > 0 THEN 100
        ELSE 0
    END AS growth_pct,
    now()
FROM stats;
""")


FACET_YEAR_SQL = text("""
INSERT INTO paper_facet_year_summary (
    facet_type,
    facet_value,
    year,
    paper_count,
    total_citations,
    avg_paper_citations,
    refreshed_at
)
SELECT
    pf.facet_type,
    pf.facet_value,
    p.year,
    COUNT(DISTINCT pf.paper_id)::bigint AS paper_count,
    COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
    COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
    now()
FROM paper_facets pf
JOIN papers p ON p.id = pf.paper_id
WHERE p.year IS NOT NULL
  AND p.year <= 2026
GROUP BY pf.facet_type, pf.facet_value, p.year
""")


COUNT_SQL = text("""
SELECT 'publication_country_stats' AS table_name, COUNT(*) FROM publication_country_stats
UNION ALL
SELECT 'publication_institution_stats' AS table_name, COUNT(*) FROM publication_institution_stats
UNION ALL
SELECT 'paper_facet_summary' AS table_name, COUNT(*) FROM paper_facet_summary
UNION ALL
SELECT 'paper_facet_year_summary' AS table_name, COUNT(*) FROM paper_facet_year_summary
ORDER BY table_name
""")

TRUNCATE_SQL = {
    "publication_country_stats": text("TRUNCATE publication_country_stats"),
    "publication_institution_stats": text("TRUNCATE publication_institution_stats"),
    "paper_facet_summary": text("TRUNCATE paper_facet_summary"),
    "paper_facet_year_summary": text("TRUNCATE paper_facet_year_summary"),
}


async def main() -> None:
    async with AsyncSessionLocal() as db:
        print("refreshing publication_country_stats...", flush=True)
        await db.execute(TRUNCATE_SQL["publication_country_stats"])
        await db.execute(COUNTRY_SQL)
        await db.commit()

        print("refreshing publication_institution_stats...", flush=True)
        await db.execute(TRUNCATE_SQL["publication_institution_stats"])
        await db.execute(INSTITUTION_SQL)
        await db.commit()

        print("refreshing paper_facet_summary...", flush=True)
        await db.execute(TRUNCATE_SQL["paper_facet_summary"])
        await db.execute(FACET_SQL)
        await db.commit()

        print("refreshing paper_facet_year_summary...", flush=True)
        await db.execute(TRUNCATE_SQL["paper_facet_year_summary"])
        await db.execute(FACET_YEAR_SQL)
        await db.commit()

        rows = (await db.execute(COUNT_SQL)).fetchall()

    print("summary refresh complete")
    for row in rows:
        print(f"{row.table_name}: {int(row.count):,}")


if __name__ == "__main__":
    asyncio.run(main())
