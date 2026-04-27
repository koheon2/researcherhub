"""
Backfill conservative paper quality flags without changing raw papers.

Usage:
    cd backend
    .venv/bin/python -m scripts.backfill_paper_quality_flags
    .venv/bin/python -m scripts.backfill_paper_quality_flags --rules future_year,pre_1900_year
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


CURRENT_YEAR = datetime.now().year
SOURCE = "conservative_v0"
EXPENSIVE_RULES = {"missing_abstract"}


FLAG_SQL = {
    "future_year": text("""
        INSERT INTO paper_quality_flags (
            paper_id, flag_type, severity, reason, source, observed_at
        )
        SELECT
            id,
            'future_year',
            'exclude',
            'paper year is after current year ' || CAST(:current_year AS integer),
            :source,
            now()
        FROM papers
        WHERE year > CAST(:current_year AS integer)
        ON CONFLICT ON CONSTRAINT uq_paper_quality_flags_identity DO UPDATE
        SET severity = EXCLUDED.severity,
            reason = EXCLUDED.reason
    """),
    "pre_1900_year": text("""
        INSERT INTO paper_quality_flags (
            paper_id, flag_type, severity, reason, source, observed_at
        )
        SELECT
            id,
            'pre_1900_year',
            'exclude',
            'paper year is before 1900',
            :source,
            now()
        FROM papers
        WHERE year < 1900
        ON CONFLICT ON CONSTRAINT uq_paper_quality_flags_identity DO UPDATE
        SET severity = EXCLUDED.severity,
            reason = EXCLUDED.reason
    """),
    "excluded_type": text("""
        INSERT INTO paper_quality_flags (
            paper_id, flag_type, severity, reason, source, observed_at
        )
        SELECT
            id,
            'excluded_type',
            'exclude',
            'paper type is ' || COALESCE(type, '<null>'),
            :source,
            now()
        FROM papers
        WHERE lower(type) IN (
            'dataset',
            'software',
            'database',
            'libguides',
            'peer-review',
            'retraction',
            'erratum'
        )
        ON CONFLICT ON CONSTRAINT uq_paper_quality_flags_identity DO UPDATE
        SET severity = EXCLUDED.severity,
            reason = EXCLUDED.reason
    """),
    "repository_doi": text("""
        INSERT INTO paper_quality_flags (
            paper_id, flag_type, severity, reason, source, observed_at
        )
        SELECT
            id,
            'repository_doi',
            'warning',
            'DOI prefix is usually a repository record',
            :source,
            now()
        FROM papers
        WHERE lower(doi) LIKE '10.5281/zenodo.%'
           OR lower(doi) LIKE '10.17632/%'
           OR lower(doi) LIKE '10.6084/m9.figshare.%'
        ON CONFLICT ON CONSTRAINT uq_paper_quality_flags_identity DO UPDATE
        SET severity = EXCLUDED.severity,
            reason = EXCLUDED.reason
    """),
    "suspicious_openalex_topic": text("""
        INSERT INTO paper_quality_flags (
            paper_id, flag_type, severity, reason, source, observed_at
        )
        SELECT
            id,
            'suspicious_openalex_topic',
            'warning',
            'OpenAlex topic Geochemistry and Geologic Mapping appears under AI/CV',
            :source,
            now()
        FROM papers
        WHERE subfield IN (
            'Artificial Intelligence',
            'Computer Vision and Pattern Recognition'
        )
          AND topic = 'Geochemistry and Geologic Mapping'
        ON CONFLICT ON CONSTRAINT uq_paper_quality_flags_identity DO UPDATE
        SET severity = EXCLUDED.severity,
            reason = EXCLUDED.reason
    """),
    "missing_abstract": text("""
        INSERT INTO paper_quality_flags (
            paper_id, flag_type, severity, reason, source, observed_at
        )
        SELECT
            id,
            'missing_abstract',
            'warning',
            'paper has no abstract text',
            :source,
            now()
        FROM papers
        WHERE abstract IS NULL OR abstract = ''
        ON CONFLICT ON CONSTRAINT uq_paper_quality_flags_identity DO UPDATE
        SET severity = EXCLUDED.severity,
            reason = EXCLUDED.reason
    """),
}

COUNT_SQL = text("""
SELECT severity, flag_type, COUNT(*) AS n
FROM paper_quality_flags
WHERE source = :source
GROUP BY severity, flag_type
ORDER BY severity, flag_type
""")

TOTAL_SQL = text("""
SELECT
    COUNT(*) AS flag_rows,
    COUNT(DISTINCT paper_id) AS flagged_papers,
    COUNT(DISTINCT paper_id) FILTER (WHERE severity = 'exclude') AS excluded_papers
FROM paper_quality_flags
WHERE source = :source
""")

PAPER_TOTAL_SQL = text("SELECT COUNT(*) FROM papers")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--current-year",
        type=int,
        default=CURRENT_YEAR,
        help="Year used to flag future records. Defaults to the local current year.",
    )
    parser.add_argument(
        "--rules",
        help=(
            "Comma-separated quality rules to run. "
            f"Defaults to all rules: {','.join(FLAG_SQL.keys())}"
        ),
    )
    return parser.parse_args()


def parse_rules(raw_rules: str | None) -> list[str]:
    if not raw_rules:
        return list(FLAG_SQL.keys())

    requested = [rule.strip() for rule in raw_rules.split(",") if rule.strip()]
    unknown = sorted(set(requested) - set(FLAG_SQL))
    if unknown:
        valid = ", ".join(FLAG_SQL.keys())
        raise SystemExit(f"Unknown quality rule(s): {', '.join(unknown)}. Valid rules: {valid}")
    return requested


async def main() -> None:
    args = parse_args()
    rules = parse_rules(args.rules)
    params = {
        "current_year": args.current_year,
        "source": SOURCE,
    }

    async with AsyncSessionLocal() as db:
        paper_total = int(await db.scalar(PAPER_TOTAL_SQL) or 0)
        print(
            "quality flag backfill is idempotent; interrupted runs can be safely resumed",
            flush=True,
        )
        print(f"rules: {', '.join(rules)}", flush=True)
        for name in rules:
            marker = " (expensive warning rule)" if name in EXPENSIVE_RULES else ""
            print(f"backfilling {name}{marker}...", flush=True)
            statement = FLAG_SQL[name]
            await db.execute(statement, params)
            await db.commit()

        totals = (await db.execute(TOTAL_SQL, {"source": SOURCE})).one()._mapping
        rows = (await db.execute(COUNT_SQL, {"source": SOURCE})).fetchall()

    excluded = int(totals["excluded_papers"] or 0)
    included = paper_total - excluded
    print("\npaper quality flag backfill complete")
    print(f"papers total:       {paper_total:,}")
    print(f"excluded papers:    {excluded:,}")
    print(f"included papers:    {included:,}")
    print(f"flagged papers:     {int(totals['flagged_papers'] or 0):,}")
    print(f"flag rows:          {int(totals['flag_rows'] or 0):,}")
    print("\nflag distribution")
    for row in rows:
        print(f"  {row.severity} / {row.flag_type}: {int(row.n):,}")


if __name__ == "__main__":
    asyncio.run(main())
