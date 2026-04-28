"""
Refresh API summary tables from publication-time paper data.

Usage:
    cd backend
    .venv/bin/python -m scripts.refresh_publication_summaries
"""

from __future__ import annotations

import asyncio
import argparse

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
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
),
stats AS (
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
    LEFT JOIN excluded e ON e.paper_id = p.id
    WHERE paa.country_code IS NOT NULL
      AND paa.country_code <> ''
      AND e.paper_id IS NULL
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
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
),
stats AS (
    SELECT
        CASE
            WHEN inm.status = 'matched' AND inm.canonical_name IS NOT NULL
                THEN inm.canonical_name
            ELSE paa.institution_name
        END AS institution_name,
        COUNT(*)::bigint AS contributions,
        COUNT(DISTINCT paa.paper_id)::bigint AS papers,
        COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
        COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
        MIN(paa.publication_year) AS min_year,
        MAX(paa.publication_year) AS max_year
    FROM paper_author_affiliations paa
    JOIN papers p ON p.id = paa.paper_id
    LEFT JOIN excluded e ON e.paper_id = p.id
    LEFT JOIN institution_name_matches inm
      ON inm.raw_institution_name = paa.institution_name
     AND inm.country_code = paa.country_code
    WHERE paa.institution_name IS NOT NULL
      AND paa.institution_name <> ''
      AND e.paper_id IS NULL
    GROUP BY
        CASE
            WHEN inm.status = 'matched' AND inm.canonical_name IS NOT NULL
                THEN inm.canonical_name
            ELSE paa.institution_name
        END
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

INSTITUTION_FIELD_SQL = text("""
INSERT INTO publication_institution_field_stats (
    institution_name,
    subfield,
    institution_ror_id,
    institution_match_confidence,
    institution_normalized,
    contributions,
    papers,
    total_citations,
    avg_paper_citations,
    min_year,
    max_year,
    refreshed_at
)
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
),
normalized AS (
    SELECT
        CASE
            WHEN inm.status = 'matched' AND inm.canonical_name IS NOT NULL
                THEN inm.canonical_name
            ELSE paa.institution_name
        END AS institution_name,
        p.subfield,
        inm.institution_ror_id,
        inm.confidence,
        (inm.status = 'matched' AND inm.canonical_name IS NOT NULL) AS institution_normalized,
        paa.id AS affiliation_id,
        paa.paper_id,
        p.citations,
        paa.publication_year
    FROM paper_author_affiliations paa
    JOIN papers p ON p.id = paa.paper_id
    LEFT JOIN excluded e ON e.paper_id = p.id
    LEFT JOIN institution_name_matches inm
      ON inm.raw_institution_name = paa.institution_name
     AND inm.country_code = paa.country_code
    WHERE paa.institution_name IS NOT NULL
      AND paa.institution_name <> ''
      AND p.subfield IS NOT NULL
      AND p.subfield <> ''
      AND e.paper_id IS NULL
)
SELECT
    institution_name,
    subfield,
    MAX(institution_ror_id) FILTER (
        WHERE institution_normalized
          AND institution_ror_id IS NOT NULL
          AND institution_ror_id <> ''
    ) AS institution_ror_id,
    MAX(confidence) FILTER (WHERE institution_normalized) AS institution_match_confidence,
    BOOL_OR(institution_normalized) AS institution_normalized,
    COUNT(affiliation_id)::bigint AS contributions,
    COUNT(DISTINCT paper_id)::bigint AS papers,
    COALESCE(SUM(citations), 0)::bigint AS total_citations,
    COALESCE(AVG(citations), 0)::float AS avg_paper_citations,
    MIN(publication_year) AS min_year,
    MAX(publication_year) AS max_year,
    now()
FROM normalized
GROUP BY institution_name, subfield
""")

COUNTRY_YEAR_SQL = text("""
INSERT INTO publication_country_year_stats (
    country_code,
    year,
    contributions,
    papers,
    total_citations,
    avg_paper_citations,
    refreshed_at
)
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
)
SELECT
    paa.country_code,
    paa.publication_year AS year,
    COUNT(*)::bigint AS contributions,
    COUNT(DISTINCT paa.paper_id)::bigint AS papers,
    COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
    COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
    now()
FROM paper_author_affiliations paa
JOIN papers p ON p.id = paa.paper_id
LEFT JOIN excluded e ON e.paper_id = p.id
WHERE paa.country_code IS NOT NULL
  AND paa.country_code <> ''
  AND paa.publication_year IS NOT NULL
  AND paa.publication_year <= EXTRACT(YEAR FROM CURRENT_DATE)::int
  AND e.paper_id IS NULL
GROUP BY paa.country_code, paa.publication_year
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
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
),
max_year AS (
    SELECT MAX(year) AS y
    FROM papers
    LEFT JOIN excluded e ON e.paper_id = papers.id
    WHERE year IS NOT NULL
      AND year <= EXTRACT(YEAR FROM CURRENT_DATE)::int
      AND e.paper_id IS NULL
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
    LEFT JOIN excluded e ON e.paper_id = p.id
    WHERE e.paper_id IS NULL
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
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
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
LEFT JOIN excluded e ON e.paper_id = p.id
WHERE p.year IS NOT NULL
  AND p.year <= EXTRACT(YEAR FROM CURRENT_DATE)::int
  AND e.paper_id IS NULL
GROUP BY pf.facet_type, pf.facet_value, p.year
""")

AUTHOR_COUNTRY_YEAR_SQL = text("""
INSERT INTO publication_author_country_year_stats (
    country_code,
    author_id,
    year,
    author_name,
    institution_name,
    contributions,
    papers,
    total_citations,
    avg_paper_citations,
    refreshed_at
)
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
)
SELECT
    paa.country_code,
    paa.author_id,
    paa.publication_year AS year,
    MAX(paa.author_name) AS author_name,
    MAX(paa.institution_name) AS institution_name,
    COUNT(*)::bigint AS contributions,
    COUNT(DISTINCT paa.paper_id)::bigint AS papers,
    COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
    COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
    now()
FROM paper_author_affiliations paa
JOIN papers p ON p.id = paa.paper_id
LEFT JOIN excluded e ON e.paper_id = p.id
WHERE paa.country_code IS NOT NULL
  AND paa.country_code <> ''
  AND paa.author_id IS NOT NULL
  AND paa.author_id <> ''
  AND paa.publication_year IS NOT NULL
  AND paa.publication_year <= EXTRACT(YEAR FROM CURRENT_DATE)::int
  AND e.paper_id IS NULL
GROUP BY paa.country_code, paa.author_id, paa.publication_year
""")

AUTHOR_FACET_YEAR_SQL = text("""
INSERT INTO publication_author_facet_year_stats (
    country_code,
    facet_type,
    facet_value,
    author_id,
    year,
    author_name,
    institution_name,
    contributions,
    papers,
    total_citations,
    avg_paper_citations,
    refreshed_at
)
WITH excluded AS (
    SELECT DISTINCT paper_id
    FROM paper_quality_flags
    WHERE severity = 'exclude'
)
SELECT
    paa.country_code,
    pf.facet_type,
    pf.facet_value,
    paa.author_id,
    paa.publication_year AS year,
    MAX(paa.author_name) AS author_name,
    MAX(paa.institution_name) AS institution_name,
    COUNT(*)::bigint AS contributions,
    COUNT(DISTINCT paa.paper_id)::bigint AS papers,
    COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
    COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
    now()
FROM paper_facets pf
JOIN papers p ON p.id = pf.paper_id
JOIN paper_author_affiliations paa ON paa.paper_id = pf.paper_id
LEFT JOIN excluded e ON e.paper_id = p.id
WHERE pf.facet_type IN ('method', 'task', 'application')
  AND paa.country_code IS NOT NULL
  AND paa.country_code <> ''
  AND paa.author_id IS NOT NULL
  AND paa.author_id <> ''
  AND paa.publication_year IS NOT NULL
  AND paa.publication_year <= EXTRACT(YEAR FROM CURRENT_DATE)::int
  AND e.paper_id IS NULL
GROUP BY
    paa.country_code,
    pf.facet_type,
    pf.facet_value,
    paa.author_id,
    paa.publication_year
""")

COUNT_SQL = text("""
SELECT 'publication_country_stats' AS table_name, COUNT(*) FROM publication_country_stats
UNION ALL
SELECT 'publication_institution_stats' AS table_name, COUNT(*) FROM publication_institution_stats
UNION ALL
SELECT 'publication_institution_field_stats' AS table_name, COUNT(*) FROM publication_institution_field_stats
UNION ALL
SELECT 'publication_country_year_stats' AS table_name, COUNT(*) FROM publication_country_year_stats
UNION ALL
SELECT 'paper_facet_summary' AS table_name, COUNT(*) FROM paper_facet_summary
UNION ALL
SELECT 'paper_facet_year_summary' AS table_name, COUNT(*) FROM paper_facet_year_summary
UNION ALL
SELECT 'publication_author_country_year_stats' AS table_name, COUNT(*) FROM publication_author_country_year_stats
UNION ALL
SELECT 'publication_author_facet_year_stats' AS table_name, COUNT(*) FROM publication_author_facet_year_stats
ORDER BY table_name
""")

QUALITY_COUNT_SQL = text("""
SELECT
    (SELECT COUNT(*) FROM papers) AS total_papers,
    (
        SELECT COUNT(DISTINCT paper_id)
        FROM paper_quality_flags
        WHERE severity = 'exclude'
    ) AS excluded_papers
""")

TRUNCATE_SQL = {
    "publication_country_stats": text("TRUNCATE publication_country_stats"),
    "publication_country_year_stats": text("TRUNCATE publication_country_year_stats"),
    "publication_institution_stats": text("TRUNCATE publication_institution_stats"),
    "publication_institution_field_stats": text("TRUNCATE publication_institution_field_stats"),
    "paper_facet_summary": text("TRUNCATE paper_facet_summary"),
    "paper_facet_year_summary": text("TRUNCATE paper_facet_year_summary"),
    "publication_author_country_year_stats": text("TRUNCATE publication_author_country_year_stats"),
    "publication_author_facet_year_stats": text("TRUNCATE publication_author_facet_year_stats"),
}


def _should_refresh(only: set[str] | None, table_name: str) -> bool:
    return only is None or table_name in only


async def main(only: set[str] | None = None) -> None:
    async with AsyncSessionLocal() as db:
        quality_counts = (await db.execute(QUALITY_COUNT_SQL)).one()._mapping
        total_papers = int(quality_counts["total_papers"] or 0)
        excluded_papers = int(quality_counts["excluded_papers"] or 0)
        included_papers = total_papers - excluded_papers

        print(
            "quality filter conservative_v0: "
            f"included={included_papers:,}, excluded={excluded_papers:,}",
            flush=True,
        )

        if _should_refresh(only, "publication_country_stats"):
            print("refreshing publication_country_stats...", flush=True)
            await db.execute(TRUNCATE_SQL["publication_country_stats"])
            await db.execute(COUNTRY_SQL)
            await db.commit()

        if _should_refresh(only, "publication_institution_stats"):
            print("refreshing publication_institution_stats...", flush=True)
            await db.execute(TRUNCATE_SQL["publication_institution_stats"])
            await db.execute(INSTITUTION_SQL)
            await db.commit()

        if _should_refresh(only, "publication_institution_field_stats"):
            print("refreshing publication_institution_field_stats...", flush=True)
            await db.execute(TRUNCATE_SQL["publication_institution_field_stats"])
            await db.execute(INSTITUTION_FIELD_SQL)
            await db.commit()

        if _should_refresh(only, "publication_country_year_stats"):
            print("refreshing publication_country_year_stats...", flush=True)
            await db.execute(TRUNCATE_SQL["publication_country_year_stats"])
            await db.execute(COUNTRY_YEAR_SQL)
            await db.commit()

        if _should_refresh(only, "paper_facet_summary"):
            print("refreshing paper_facet_summary...", flush=True)
            await db.execute(TRUNCATE_SQL["paper_facet_summary"])
            await db.execute(FACET_SQL)
            await db.commit()

        if _should_refresh(only, "paper_facet_year_summary"):
            print("refreshing paper_facet_year_summary...", flush=True)
            await db.execute(TRUNCATE_SQL["paper_facet_year_summary"])
            await db.execute(FACET_YEAR_SQL)
            await db.commit()

        if _should_refresh(only, "publication_author_country_year_stats"):
            print("refreshing publication_author_country_year_stats...", flush=True)
            await db.execute(TRUNCATE_SQL["publication_author_country_year_stats"])
            await db.execute(AUTHOR_COUNTRY_YEAR_SQL)
            await db.commit()

        if _should_refresh(only, "publication_author_facet_year_stats"):
            print("refreshing publication_author_facet_year_stats...", flush=True)
            await db.execute(TRUNCATE_SQL["publication_author_facet_year_stats"])
            await db.execute(AUTHOR_FACET_YEAR_SQL)
            await db.commit()

        rows = (await db.execute(COUNT_SQL)).fetchall()

    print("summary refresh complete")
    for row in rows:
        print(f"{row.table_name}: {int(row.count):,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        help="Comma-separated summary table names to refresh. Defaults to all.",
    )
    args = parser.parse_args()
    only = {name.strip() for name in args.only.split(",") if name.strip()} if args.only else None
    asyncio.run(main(only))
