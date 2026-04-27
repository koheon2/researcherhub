"""
Profile paper metadata quality without mutating the database.

Usage:
    cd backend
    .venv/bin/python -m scripts.validate_metadata_quality
    .venv/bin/python -m scripts.validate_metadata_quality --external-sample 50 --csv /tmp/audit.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


CURRENT_YEAR = datetime.now().year
USER_AGENT = "ResearcherHub-metadata-audit/0.1"

COUNT_SQL = text("SELECT COUNT(*) FROM papers")
ESTIMATED_COUNT_SQL = text("""
SELECT GREATEST(reltuples::bigint, 0)
FROM pg_class
WHERE oid = to_regclass(:table_name)
""")

YEAR_MISSING_SQL = text("SELECT COUNT(*) FROM papers WHERE year IS NULL")
YEAR_OLD_SQL = text("SELECT COUNT(*) FROM papers WHERE year < 1900")
YEAR_FUTURE_SQL = text("SELECT COUNT(*) FROM papers WHERE year > :current_year")
YEAR_MIN_SQL = text("SELECT year FROM papers WHERE year IS NOT NULL ORDER BY year ASC LIMIT 1")
YEAR_MAX_SQL = text("SELECT year FROM papers WHERE year IS NOT NULL ORDER BY year DESC LIMIT 1")
YEAR_SAMPLE_SQL = text("""
SELECT
    COUNT(*) AS sample_rows,
    COUNT(*) FILTER (WHERE year IS NULL) AS missing_year,
    COUNT(*) FILTER (WHERE year < 1900) AS old_year,
    COUNT(*) FILTER (WHERE year > :current_year) AS future_year
FROM papers TABLESAMPLE SYSTEM (:sample_percent)
""")

TYPE_COUNTS_SQL = text("""
SELECT COALESCE(type, '<null>') AS type, COUNT(*) AS n
FROM papers
GROUP BY type
ORDER BY n DESC
LIMIT :limit
""")

TYPE_COUNTS_SAMPLE_SQL = text("""
SELECT COALESCE(type, '<null>') AS type, COUNT(*) AS n
FROM papers TABLESAMPLE SYSTEM (:sample_percent)
GROUP BY type
ORDER BY n DESC
LIMIT :limit
""")

DOI_BUCKET_SQL = text("""
SELECT
    CASE
        WHEN doi IS NULL OR doi = '' THEN 'no_doi'
        WHEN lower(doi) LIKE '10.5281/zenodo.%' THEN 'zenodo'
        WHEN lower(doi) LIKE '10.17632/%' THEN 'mendeley_data'
        WHEN lower(doi) LIKE '10.6084/m9.figshare.%' THEN 'figshare'
        WHEN lower(doi) LIKE '10.11588/diglit.%' THEN 'heidelberg_digital'
        ELSE 'other_doi'
    END AS bucket,
    COUNT(*) AS papers,
    COUNT(*) FILTER (WHERE year > :current_year) AS future_year,
    COUNT(*) FILTER (WHERE year < 1900) AS old_year,
    COUNT(*) FILTER (WHERE abstract IS NULL OR abstract = '') AS missing_abstract
FROM papers
GROUP BY bucket
ORDER BY papers DESC
""")

DOI_BUCKET_SAMPLE_SQL = text("""
SELECT
    CASE
        WHEN doi IS NULL OR doi = '' THEN 'no_doi'
        WHEN lower(doi) LIKE '10.5281/zenodo.%' THEN 'zenodo'
        WHEN lower(doi) LIKE '10.17632/%' THEN 'mendeley_data'
        WHEN lower(doi) LIKE '10.6084/m9.figshare.%' THEN 'figshare'
        WHEN lower(doi) LIKE '10.11588/diglit.%' THEN 'heidelberg_digital'
        ELSE 'other_doi'
    END AS bucket,
    COUNT(*) AS papers,
    COUNT(*) FILTER (WHERE year > :current_year) AS future_year,
    COUNT(*) FILTER (WHERE year < 1900) AS old_year,
    COUNT(*) FILTER (WHERE abstract IS NULL OR abstract = '') AS missing_abstract
FROM papers TABLESAMPLE SYSTEM (:sample_percent)
GROUP BY bucket
ORDER BY papers DESC
""")

COVERAGE_SAMPLE_SQL = text("""
SELECT
    COUNT(*) AS sample_rows,
    COUNT(*) FILTER (WHERE abstract IS NULL OR abstract = '') AS missing_abstract,
    COUNT(*) FILTER (WHERE doi IS NULL OR doi = '') AS missing_doi
FROM papers TABLESAMPLE SYSTEM (:sample_percent)
""")

AFFILIATION_COVERAGE_SQL = text("""
SELECT
    COUNT(*) AS source_rows,
    COUNT(*) FILTER (
        WHERE institution_name IS NULL OR institution_name = ''
    ) AS missing_institution,
    COUNT(*) FILTER (
        WHERE country IS NULL OR country = ''
    ) AS missing_country
FROM paper_authors
""")

AFFILIATION_COVERAGE_SAMPLE_SQL = text("""
SELECT
    COUNT(*) AS source_rows,
    COUNT(*) FILTER (
        WHERE institution_name IS NULL OR institution_name = ''
    ) AS missing_institution,
    COUNT(*) FILTER (
        WHERE country IS NULL OR country = ''
    ) AS missing_country
FROM paper_authors TABLESAMPLE SYSTEM (:sample_percent)
""")

AFFILIATION_TARGET_SQL = text("""
SELECT
    COUNT(*) AS target_rows,
    COUNT(*) FILTER (WHERE publication_year IS NULL) AS missing_year,
    MIN(publication_year) AS min_year,
    MAX(publication_year) AS max_year,
    COUNT(*) FILTER (WHERE publication_year > :current_year) AS future_year
FROM paper_author_affiliations
""")

AFFILIATION_TARGET_SAMPLE_SQL = text("""
SELECT
    COUNT(*) AS target_rows,
    COUNT(*) FILTER (WHERE publication_year IS NULL) AS missing_year,
    MIN(publication_year) AS min_year,
    MAX(publication_year) AS max_year,
    COUNT(*) FILTER (WHERE publication_year > :current_year) AS future_year
FROM paper_author_affiliations TABLESAMPLE SYSTEM (:sample_percent)
""")

SUSPICIOUS_TOPIC_SQL = text("""
SELECT
    COUNT(*) AS papers,
    COUNT(*) FILTER (WHERE topic = 'Geochemistry and Geologic Mapping') AS geochemistry_topic,
    COUNT(*) FILTER (WHERE topic = 'History of Computing Technologies') AS history_topic
FROM papers
WHERE subfield IN ('Artificial Intelligence', 'Computer Vision and Pattern Recognition')
""")

SUSPICIOUS_TOPIC_SAMPLE_SQL = text("""
SELECT
    COUNT(*) AS papers,
    COUNT(*) FILTER (WHERE topic = 'Geochemistry and Geologic Mapping') AS geochemistry_topic,
    COUNT(*) FILTER (WHERE topic = 'History of Computing Technologies') AS history_topic
FROM papers TABLESAMPLE SYSTEM (:sample_percent)
WHERE subfield IN ('Artificial Intelligence', 'Computer Vision and Pattern Recognition')
""")

EXTERNAL_SAMPLE_SQL = text("""
WITH source AS (
    SELECT
        'normal_article' AS bucket,
        id,
        title,
        doi,
        year,
        type,
        subfield,
        topic
    FROM papers TABLESAMPLE SYSTEM (0.2)
    WHERE year BETWEEN :start_year AND :current_year
      AND type = 'article'
      AND doi IS NOT NULL
      AND doi <> ''
    LIMIT :normal_limit
), future AS (
    SELECT
        'future' AS bucket,
        id,
        title,
        doi,
        year,
        type,
        subfield,
        topic
    FROM papers
    WHERE year > :current_year
      AND doi IS NOT NULL
      AND doi <> ''
    ORDER BY year DESC
    LIMIT :future_limit
), repository AS (
    SELECT
        'repository' AS bucket,
        id,
        title,
        doi,
        year,
        type,
        subfield,
        topic
    FROM papers TABLESAMPLE SYSTEM (0.5)
    WHERE (
        type = 'dataset'
        OR lower(doi) LIKE '10.5281/zenodo.%'
        OR lower(doi) LIKE '10.17632/%'
        OR lower(doi) LIKE '10.6084/m9.figshare.%'
    )
      AND doi IS NOT NULL
      AND doi <> ''
    LIMIT :repository_limit
)
SELECT * FROM source
UNION ALL SELECT * FROM future
UNION ALL SELECT * FROM repository
LIMIT :limit
""")


@dataclass
class PaperSample:
    bucket: str
    id: str
    title: str
    doi: str
    year: int | None
    type: str | None
    subfield: str | None
    topic: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile paper metadata quality without mutating the database."
    )
    parser.add_argument(
        "--coverage-sample-percent",
        type=float,
        default=2.0,
        help="TABLESAMPLE percent for abstract/DOI coverage estimates.",
    )
    parser.add_argument(
        "--external-sample",
        type=int,
        default=0,
        help="If > 0, compare this many sampled DOI records against Crossref/DataCite.",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Run full-table DOI bucket and paper_authors coverage scans. Default uses samples.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Optional CSV path for external audit rows.",
    )
    return parser.parse_args()


def pct(part: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{(part / total) * 100:.2f}%"


def print_rows(title: str, rows: list[Any], columns: list[str]) -> None:
    print(f"\n{title}")
    if not rows:
        print("  none")
        return
    for row in rows:
        data = row._mapping
        parts = [f"{column}={data[column]}" for column in columns]
        print("  " + ", ".join(parts))


def fetch_json(url: str) -> dict[str, Any] | None:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def crossref_year(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        value = message.get(key)
        if not isinstance(value, dict):
            continue
        date_parts = value.get("date-parts")
        if not date_parts:
            continue
        try:
            return int(date_parts[0][0])
        except (TypeError, ValueError, IndexError):
            continue
    return None


def normalize_title(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def title_overlap(left: str | None, right: str | None) -> float:
    left_words = set(normalize_title(left).split())
    right_words = set(normalize_title(right).split())
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / max(1, min(len(left_words), len(right_words)))


def external_lookup(doi: str) -> dict[str, Any]:
    doi_url = quote(doi.lower(), safe="")

    crossref = fetch_json(f"https://api.crossref.org/works/{doi_url}")
    if crossref and isinstance(crossref.get("message"), dict):
        message = crossref["message"]
        return {
            "provider": "crossref",
            "title": (message.get("title") or [""])[0],
            "year": crossref_year(message),
            "type": message.get("type") or "",
            "publisher": message.get("publisher") or "",
        }

    datacite = fetch_json(f"https://api.datacite.org/dois/{doi_url}")
    if datacite and isinstance(datacite.get("data"), dict):
        attrs = datacite["data"].get("attributes") or {}
        titles = attrs.get("titles") or [{}]
        types = attrs.get("types") or {}
        published = attrs.get("published")
        return {
            "provider": "datacite",
            "title": titles[0].get("title", "") if titles else "",
            "year": int(published) if str(published).isdigit() else None,
            "type": types.get("resourceTypeGeneral") or types.get("resourceType") or "",
            "publisher": attrs.get("publisher") or "",
        }

    return {
        "provider": "missing",
        "title": "",
        "year": None,
        "type": "",
        "publisher": "",
    }


def classify_external(sample: PaperSample, external: dict[str, Any]) -> tuple[str, list[str]]:
    flags: list[str] = []
    provider = external.get("provider")
    external_year = external.get("year")
    external_type = str(external.get("type") or "").lower()

    if provider == "missing":
        return "external_missing", ["external_missing"]

    if external_year and sample.year and external_year != sample.year:
        flags.append("year_mismatch")
    if external.get("title") and title_overlap(sample.title, external.get("title")) < 0.45:
        flags.append("title_mismatch")
    if sample.year and sample.year > CURRENT_YEAR:
        flags.append("future_year")
    if sample.year and sample.year < 1900:
        flags.append("pre_1900_year")

    doi = sample.doi.lower()
    repository_doi = doi.startswith(
        ("10.5281/zenodo.", "10.17632/", "10.6084/m9.figshare.")
    )
    repository_type = (sample.type or "").lower() in {
        "dataset",
        "software",
        "database",
        "libguides",
        "standard",
        "peer-review",
        "paratext",
        "retraction",
        "erratum",
    }
    if repository_doi or repository_type or external_type in {"dataset", "model", "other"}:
        flags.append("likely_non_research_or_repository")

    if sample.topic in {"Geochemistry and Geologic Mapping", "History of Computing Technologies"}:
        flags.append("topic_suspicious")

    if not flags:
        return "consistent_enough", []

    severe = {
        "future_year",
        "pre_1900_year",
        "likely_non_research_or_repository",
        "title_mismatch",
    }
    if severe & set(flags):
        return "problematic", flags
    return "minor_issue", flags


async def load_external_samples(limit: int) -> list[PaperSample]:
    normal_limit = max(1, limit // 3)
    future_limit = max(1, limit // 3)
    repository_limit = max(1, limit - normal_limit - future_limit)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            EXTERNAL_SAMPLE_SQL,
            {
                "start_year": CURRENT_YEAR - 9,
                "current_year": CURRENT_YEAR,
                "normal_limit": normal_limit,
                "future_limit": future_limit,
                "repository_limit": repository_limit,
                "limit": limit,
            },
        )
        rows = result.fetchall()

    samples: list[PaperSample] = []
    seen_doi: set[str] = set()
    for row in rows:
        doi = (row.doi or "").lower()
        if not doi or doi in seen_doi:
            continue
        seen_doi.add(doi)
        samples.append(
            PaperSample(
                bucket=row.bucket,
                id=row.id,
                title=row.title or "",
                doi=doi,
                year=int(row.year) if row.year is not None else None,
                type=row.type,
                subfield=row.subfield,
                topic=row.topic,
            )
        )
    return samples[:limit]


def write_external_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "bucket",
        "paper_id",
        "doi",
        "db_year",
        "db_type",
        "subfield",
        "topic",
        "class",
        "flags",
        "provider",
        "external_year",
        "external_type",
        "external_publisher",
        "title",
        "external_title",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def run_external_audit(limit: int, csv_path: Path | None) -> int:
    samples = await load_external_samples(limit)
    if not samples:
        print("\nExternal DOI audit")
        print("  no eligible samples")
        return 0

    rows: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    provider_counts: Counter[str] = Counter()

    print(f"\nExternal DOI audit ({len(samples)} samples)")
    for index, sample in enumerate(samples, start=1):
        external = external_lookup(sample.doi)
        classification, flags = classify_external(sample, external)

        class_counts[classification] += 1
        flag_counts.update(flags)
        provider_counts[str(external.get("provider") or "missing")] += 1
        rows.append(
            {
                "bucket": sample.bucket,
                "paper_id": sample.id,
                "doi": sample.doi,
                "db_year": sample.year,
                "db_type": sample.type,
                "subfield": sample.subfield,
                "topic": sample.topic,
                "class": classification,
                "flags": "|".join(flags),
                "provider": external.get("provider"),
                "external_year": external.get("year"),
                "external_type": external.get("type"),
                "external_publisher": external.get("publisher"),
                "title": sample.title,
                "external_title": external.get("title"),
            }
        )
        if index % 25 == 0:
            print(f"  checked {index}/{len(samples)}", flush=True)

    print("\nExternal classes")
    for key, value in class_counts.most_common():
        print(f"  {key}: {value:,} ({pct(value, len(samples))})")

    print("\nExternal providers")
    for key, value in provider_counts.most_common():
        print(f"  {key}: {value:,} ({pct(value, len(samples))})")

    print("\nExternal flags")
    for key, value in flag_counts.most_common():
        print(f"  {key}: {value:,} ({pct(value, len(samples))})")

    if csv_path:
        write_external_csv(csv_path, rows)
        print(f"\nExternal audit CSV: {csv_path}")

    return 0


async def main() -> int:
    args = parse_args()
    warnings: list[str] = []

    if not 0 < args.coverage_sample_percent <= 100:
        print("--coverage-sample-percent must be between 0 and 100", file=sys.stderr)
        return 2
    if args.external_sample < 0:
        print("--external-sample must be >= 0", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as db:
        if args.deep:
            total_papers = int(await db.scalar(COUNT_SQL) or 0)
            total_is_estimated = False
            missing_year = int(await db.scalar(YEAR_MISSING_SQL) or 0)
            old_year = int(await db.scalar(YEAR_OLD_SQL) or 0)
            future_year = int(
                await db.scalar(YEAR_FUTURE_SQL, {"current_year": CURRENT_YEAR}) or 0
            )
            year_sample_rows: int | None = None
        else:
            total_papers = int(
                await db.scalar(ESTIMATED_COUNT_SQL, {"table_name": "papers"}) or 0
            )
            total_is_estimated = True
            year_quality = (
                await db.execute(
                    YEAR_SAMPLE_SQL,
                    {
                        "current_year": CURRENT_YEAR,
                        "sample_percent": args.coverage_sample_percent,
                    },
                )
            ).one()._mapping
            year_sample_rows = int(year_quality["sample_rows"] or 0)
            missing_year = int(year_quality["missing_year"] or 0)
            old_year = int(year_quality["old_year"] or 0)
            future_year = int(year_quality["future_year"] or 0)
        min_year = await db.scalar(YEAR_MIN_SQL)
        max_year = await db.scalar(YEAR_MAX_SQL)
        if args.deep:
            type_counts = (
                await db.execute(TYPE_COUNTS_SQL, {"limit": 25})
            ).fetchall()
        else:
            type_counts = (
                await db.execute(
                    TYPE_COUNTS_SAMPLE_SQL,
                    {
                        "limit": 25,
                        "sample_percent": args.coverage_sample_percent,
                    },
                )
            ).fetchall()
        if args.deep:
            doi_buckets = (
                await db.execute(DOI_BUCKET_SQL, {"current_year": CURRENT_YEAR})
            ).fetchall()
        else:
            doi_buckets = (
                await db.execute(
                    DOI_BUCKET_SAMPLE_SQL,
                    {
                        "current_year": CURRENT_YEAR,
                        "sample_percent": args.coverage_sample_percent,
                    },
                )
            ).fetchall()
        coverage = (
            await db.execute(
                COVERAGE_SAMPLE_SQL,
                {"sample_percent": args.coverage_sample_percent},
            )
        ).one()._mapping
        if args.deep:
            affiliation_source = (await db.execute(AFFILIATION_COVERAGE_SQL)).one()._mapping
        else:
            affiliation_source = (
                await db.execute(
                    AFFILIATION_COVERAGE_SAMPLE_SQL,
                    {"sample_percent": args.coverage_sample_percent},
                )
            ).one()._mapping
        if args.deep:
            affiliation_target = (
                await db.execute(
                    AFFILIATION_TARGET_SQL,
                    {"current_year": CURRENT_YEAR},
                )
            ).one()._mapping
            suspicious_topics = (await db.execute(SUSPICIOUS_TOPIC_SQL)).one()._mapping
        else:
            affiliation_target = (
                await db.execute(
                    AFFILIATION_TARGET_SAMPLE_SQL,
                    {
                        "current_year": CURRENT_YEAR,
                        "sample_percent": args.coverage_sample_percent,
                    },
                )
            ).one()._mapping
            suspicious_topics = (
                await db.execute(
                    SUSPICIOUS_TOPIC_SAMPLE_SQL,
                    {"sample_percent": args.coverage_sample_percent},
                )
            ).one()._mapping

    print("Metadata quality profile")
    print(f"current_year:                   {CURRENT_YEAR}")
    total_label = "estimated" if total_is_estimated else "exact"
    print(f"papers total ({total_label}):         {total_papers:,}")
    if year_sample_rows is not None:
        print(f"year quality sample rows:       {year_sample_rows:,}")
    year_denominator = year_sample_rows if year_sample_rows is not None else total_papers
    print(
        "year missing:                   "
        f"{missing_year:,}"
    )
    print(
        "year < 1900:                    "
        f"{old_year:,} "
        f"({pct(old_year, year_denominator)})"
    )
    print(
        f"year > {CURRENT_YEAR}:                    "
        f"{future_year:,} "
        f"({pct(future_year, year_denominator)})"
    )
    print(f"year range:                     {min_year} - {max_year}")

    type_title = "Top paper types"
    if not args.deep:
        type_title += f" ({args.coverage_sample_percent:g}% TABLESAMPLE)"
    print_rows(type_title, type_counts, ["type", "n"])
    bucket_title = "DOI/source buckets"
    if not args.deep:
        bucket_title += f" ({args.coverage_sample_percent:g}% TABLESAMPLE)"
    print_rows(
        bucket_title,
        doi_buckets,
        ["bucket", "papers", "future_year", "old_year", "missing_abstract"],
    )

    sample_rows = int(coverage["sample_rows"] or 0)
    missing_abstract = int(coverage["missing_abstract"] or 0)
    missing_doi = int(coverage["missing_doi"] or 0)
    print(f"\nCoverage sample ({args.coverage_sample_percent:g}% TABLESAMPLE)")
    print(
        "  missing abstract:             "
        f"{missing_abstract:,} / {sample_rows:,} ({pct(missing_abstract, sample_rows)})"
    )
    print(
        "  missing DOI:                  "
        f"{missing_doi:,} / {sample_rows:,} ({pct(missing_doi, sample_rows)})"
    )

    source_rows = int(affiliation_source["source_rows"] or 0)
    missing_institution = int(affiliation_source["missing_institution"] or 0)
    missing_country = int(affiliation_source["missing_country"] or 0)
    target_rows = int(affiliation_target["target_rows"] or 0)
    affiliation_title = "\nAffiliation coverage"
    if not args.deep:
        affiliation_title += f" ({args.coverage_sample_percent:g}% TABLESAMPLE source estimate)"
    print(affiliation_title)
    print(f"  source paper_authors rows:    {source_rows:,}")
    print(
        "  missing institution:          "
        f"{missing_institution:,} / {source_rows:,} ({pct(missing_institution, source_rows)})"
    )
    print(
        "  missing country:              "
        f"{missing_country:,} / {source_rows:,} ({pct(missing_country, source_rows)})"
    )
    if args.deep:
        print(
            "  publication-time rows:        "
            f"{target_rows:,} / {source_rows:,} ({pct(target_rows, source_rows)})"
        )
    else:
        print(f"  publication-time sample rows: {target_rows:,}")
    print(
        "  publication-time missing year:"
        f" {int(affiliation_target['missing_year'] or 0):,}"
    )
    print(
        "  publication-time future year: "
        f"{int(affiliation_target['future_year'] or 0):,}"
    )
    print(
        "  publication-time year range:  "
        f"{affiliation_target['min_year']} - {affiliation_target['max_year']}"
    )

    ai_cv_total = int(suspicious_topics["papers"] or 0)
    geochem = int(suspicious_topics["geochemistry_topic"] or 0)
    history = int(suspicious_topics["history_topic"] or 0)
    print("\nSuspicious topic indicators")
    topic_label = "sample" if not args.deep else "inspected"
    print(f"  AI/CV papers {topic_label}:          {ai_cv_total:,}")
    print(
        "  geochemistry topic:           "
        f"{geochem:,} ({pct(geochem, ai_cv_total)})"
    )
    print(
        "  history topic:                "
        f"{history:,} ({pct(history, ai_cv_total)})"
    )

    if future_year > 0:
        warnings.append("future-year papers exist")
    if old_year > 0:
        warnings.append("pre-1900 papers exist")
    if missing_institution > 0 or missing_country > 0:
        warnings.append("paper_authors affiliation coverage is incomplete")

    if args.external_sample:
        await run_external_audit(args.external_sample, args.csv)

    if warnings:
        print("\nMetadata quality warnings")
        for warning in warnings:
            print(f"  - {warning}")

    print("\nMetadata quality profile complete")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
