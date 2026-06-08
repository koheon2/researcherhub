"""
Select high-precision paper candidates for OpenAlex reference enrichment.

This script is read-only. It does not create tables or write to the database.

Usage:
    cd backend
    .venv/bin/python -m scripts.select_reference_enrichment_candidates --limit 1000
    .venv/bin/python -m scripts.select_reference_enrichment_candidates --limit 1000 --csv /tmp/reference_candidates.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


CURRENT_YEAR = datetime.now().year
DEFAULT_METHOD_FACETS = (
    "Large Language Model",
    "Transformer",
    "Diffusion",
    "Retrieval-Augmented Generation",
    "Vision-Language Model",
    "Vision Transformer",
    "Graph Neural Network",
    "GAN",
    "CLIP",
    "Self-Supervised Learning",
    "Contrastive Learning",
    "Federated Learning",
    "Prompt Engineering",
    "Low-Rank Adaptation",
    "Mixture of Experts",
    "RLHF",
)
DEFAULT_TASK_FACETS = (
    "Reasoning",
    "Information Retrieval",
    "Object Detection",
    "Image Segmentation",
    "Code Generation",
    "Text Generation",
    "Question Answering",
    "Visual Question Answering",
    "Agent Planning",
    "Document Understanding",
)
DEFAULT_APPLICATION_FACETS = (
    "Medical Imaging",
    "Autonomous Driving",
    "Robotics",
    "Drug Discovery",
    "Recommendation Systems",
    "Cybersecurity",
    "Scientific Discovery",
)


HIGH_IMPACT_SQL = text("""
SELECT
    p.id,
    p.title,
    p.year,
    p.citations,
    p.fwci,
    p.doi,
    p.type,
    p.subfield,
    p.topic,
    p.abstract IS NOT NULL AND p.abstract <> '' AS has_abstract,
    p.open_access,
    NULL::text AS facet_type,
    NULL::text AS facet_value,
    'high_impact_ai_cv' AS bucket
FROM papers p
WHERE p.year BETWEEN :year_from AND :year_to
  AND p.subfield IN ('Artificial Intelligence', 'Computer Vision and Pattern Recognition')
  AND lower(COALESCE(p.type, '')) = ANY(:allowed_types)
  AND length(trim(COALESCE(p.title, ''))) >= :min_title_length
  AND p.citations >= :min_citations
  AND NOT EXISTS (
      SELECT 1
      FROM paper_quality_flags pqf
      WHERE pqf.paper_id = p.id
        AND pqf.severity = 'exclude'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM paper_quality_flags pqf
      WHERE pqf.paper_id = p.id
        AND pqf.flag_type IN ('repository_doi', 'suspicious_openalex_topic')
  )
ORDER BY p.citations DESC NULLS LAST, p.fwci DESC NULLS LAST, p.year DESC NULLS LAST, p.id
LIMIT :bucket_limit
""")


FACET_ANNOTATION_SQL = text("""
SELECT paper_id, facet_type, facet_value
FROM paper_facets
WHERE paper_id = ANY(:paper_ids)
  AND facet_type = ANY(:facet_types)
  AND facet_value = ANY(:facet_values)
ORDER BY paper_id, facet_type, facet_value
""")


RECENT_HOT_SQL = text("""
SELECT
    p.id,
    p.title,
    p.year,
    p.citations,
    p.fwci,
    p.doi,
    p.type,
    p.subfield,
    p.topic,
    p.abstract IS NOT NULL AND p.abstract <> '' AS has_abstract,
    p.open_access,
    NULL::text AS facet_type,
    NULL::text AS facet_value,
    'recent_hot_ai_cv' AS bucket
FROM papers p
WHERE p.year BETWEEN :recent_year_from AND :year_to
  AND p.subfield IN ('Artificial Intelligence', 'Computer Vision and Pattern Recognition')
  AND lower(COALESCE(p.type, '')) = ANY(:allowed_types)
  AND length(trim(COALESCE(p.title, ''))) >= :min_title_length
  AND p.citations >= :recent_min_citations
  AND NOT EXISTS (
      SELECT 1
      FROM paper_quality_flags pqf
      WHERE pqf.paper_id = p.id
        AND pqf.severity = 'exclude'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM paper_quality_flags pqf
      WHERE pqf.paper_id = p.id
        AND pqf.flag_type IN ('repository_doi', 'suspicious_openalex_topic')
  )
ORDER BY p.year DESC NULLS LAST, p.citations DESC NULLS LAST, p.fwci DESC NULLS LAST, p.id
LIMIT :bucket_limit
""")


@dataclass(slots=True)
class Candidate:
    id: str
    title: str
    year: int | None
    citations: int
    fwci: float | None
    doi: str | None
    type: str | None
    subfield: str | None
    topic: str | None
    has_abstract: bool
    open_access: bool
    facet_type: str | None
    facet_value: str | None
    buckets: set[str]
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000, help="Final candidate count.")
    parser.add_argument("--year-from", type=int, default=2017)
    parser.add_argument("--year-to", type=int, default=min(CURRENT_YEAR, 2026))
    parser.add_argument("--recent-year-from", type=int, default=2022)
    parser.add_argument(
        "--per-facet",
        type=int,
        default=25,
        help="Reserved for future per-facet selection. Current v0 annotates facets within high-quality pools.",
    )
    parser.add_argument("--min-title-length", type=int, default=20)
    parser.add_argument("--min-citations", type=int, default=500)
    parser.add_argument("--recent-min-citations", type=int, default=100)
    parser.add_argument(
        "--include-preprints",
        action="store_true",
        help="Include OpenAlex type=preprint. Default excludes preprints for higher precision.",
    )
    parser.add_argument(
        "--allow-missing-abstract",
        action="store_true",
        help="Allow papers without local abstract. Default requires an abstract.",
    )
    parser.add_argument(
        "--allow-without-facet",
        action="store_true",
        help="Allow final candidates without method/task/application facet annotation.",
    )
    parser.add_argument("--csv", type=Path, help="Optional CSV output path.")
    parser.add_argument("--show", type=int, default=50, help="Number of top rows to print.")
    return parser.parse_args()


def facet_pairs() -> tuple[list[str], list[str]]:
    pairs = []
    pairs.extend(("method", value) for value in DEFAULT_METHOD_FACETS)
    pairs.extend(("task", value) for value in DEFAULT_TASK_FACETS)
    pairs.extend(("application", value) for value in DEFAULT_APPLICATION_FACETS)
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def row_score(row, bucket: str) -> float:
    citations = int(row.citations or 0)
    fwci = float(row.fwci) if row.fwci is not None else 0.0
    score = math.log1p(citations) * 3.0
    score += min(fwci, 25.0) * 0.15
    if row.has_abstract:
        score += 2.0
    if row.doi:
        score += 1.0
    if row.open_access:
        score += 0.5
    if row.facet_type in {"method", "task", "application"}:
        score += 2.0
    if bucket == "facet_representative":
        score += 2.0
    if bucket == "recent_hot_ai_cv":
        score += 1.0
    if row.type == "preprint":
        score += 0.5
    return score


def upsert_candidate(pool: dict[str, Candidate], row) -> None:
    bucket = str(row.bucket)
    score = row_score(row, bucket)
    if row.id not in pool:
        pool[row.id] = Candidate(
            id=row.id,
            title=(row.title or "").strip(),
            year=row.year,
            citations=int(row.citations or 0),
            fwci=float(row.fwci) if row.fwci is not None else None,
            doi=row.doi,
            type=row.type,
            subfield=row.subfield,
            topic=row.topic,
            has_abstract=bool(row.has_abstract),
            open_access=bool(row.open_access),
            facet_type=row.facet_type,
            facet_value=row.facet_value,
            buckets={bucket},
            score=score,
        )
        return

    existing = pool[row.id]
    existing.buckets.add(bucket)
    existing.score = max(existing.score, score) + 0.75
    if existing.facet_type is None and row.facet_type:
        existing.facet_type = row.facet_type
        existing.facet_value = row.facet_value


def type_filter(include_preprints: bool) -> tuple[str, ...]:
    if include_preprints:
        return ("article", "proceedings-article", "preprint")
    return ("article", "proceedings-article")


async def fetch_candidates(args: argparse.Namespace) -> list[Candidate]:
    facet_types, facet_values = facet_pairs()
    bucket_limit = max(args.limit, 250)
    params = {
        "year_from": args.year_from,
        "year_to": args.year_to,
        "recent_year_from": args.recent_year_from,
        "per_facet": args.per_facet,
        "min_title_length": args.min_title_length,
        "min_citations": args.min_citations,
        "recent_min_citations": args.recent_min_citations,
        "bucket_limit": bucket_limit,
        "facet_types": facet_types,
        "facet_values": facet_values,
        "allowed_types": list(type_filter(args.include_preprints)),
    }

    pool: dict[str, Candidate] = {}
    async with AsyncSessionLocal() as db:
        for label, statement in (
            ("high impact AI/CV", HIGH_IMPACT_SQL),
            ("recent hot AI/CV", RECENT_HOT_SQL),
        ):
            print(f"selecting {label}...", flush=True)
            rows = (await db.execute(statement, params)).fetchall()
            print(f"  rows: {len(rows):,}", flush=True)
            for row in rows:
                upsert_candidate(pool, row)

        paper_ids = list(pool.keys())
        if paper_ids:
            print("annotating selected method/task/application facets...", flush=True)
            facet_rows = (
                await db.execute(
                    FACET_ANNOTATION_SQL,
                    {
                        "paper_ids": paper_ids,
                        "facet_types": ["method", "task", "application"],
                        "facet_values": facet_values,
                    },
                )
            ).fetchall()
            print(f"  facet annotations: {len(facet_rows):,}", flush=True)
            by_paper: dict[str, list[tuple[str, str]]] = defaultdict(list)
            for row in facet_rows:
                by_paper[row.paper_id].append((row.facet_type, row.facet_value))
            for paper_id, facets in by_paper.items():
                candidate = pool.get(paper_id)
                if not candidate:
                    continue
                candidate.buckets.add("facet_annotated")
                candidate.score += 2.0 + min(len(facets), 3) * 0.5
                if candidate.facet_type is None:
                    candidate.facet_type, candidate.facet_value = facets[0]

    candidates = list(pool.values())
    if not args.allow_missing_abstract:
        candidates = [c for c in candidates if c.has_abstract]
    if not args.allow_without_facet:
        candidates = [c for c in candidates if c.facet_type and c.facet_value]

    return sorted(candidates, key=lambda c: (-c.score, -c.citations, c.id))[: args.limit]


def print_summary(candidates: list[Candidate], show: int) -> None:
    bucket_counts = Counter()
    facet_counts = Counter()
    type_counts = Counter(c.type or "<null>" for c in candidates)
    subfield_counts = Counter(c.subfield or "<null>" for c in candidates)
    year_counts = Counter(c.year for c in candidates)
    for candidate in candidates:
        bucket_counts.update(candidate.buckets)
        if candidate.facet_type and candidate.facet_value:
            facet_counts[(candidate.facet_type, candidate.facet_value)] += 1

    total = len(candidates)
    abstract_count = sum(c.has_abstract for c in candidates)
    doi_count = sum(bool(c.doi) for c in candidates)
    oa_count = sum(c.open_access for c in candidates)

    print("\n=== Candidate summary ===")
    print(f"candidates: {total:,}")
    if total:
        print(f"abstract coverage: {abstract_count:,}/{total:,} ({abstract_count / total * 100:.2f}%)")
        print(f"doi coverage:      {doi_count:,}/{total:,} ({doi_count / total * 100:.2f}%)")
        print(f"open access:       {oa_count:,}/{total:,} ({oa_count / total * 100:.2f}%)")

    print("\nBuckets:")
    for name, count in bucket_counts.most_common():
        print(f"  {name}: {count:,}")

    print("\nTypes:")
    for name, count in type_counts.most_common():
        print(f"  {name}: {count:,}")

    print("\nSubfields:")
    for name, count in subfield_counts.most_common():
        print(f"  {name}: {count:,}")

    print("\nYears:")
    for year, count in sorted(year_counts.items()):
        print(f"  {year}: {count:,}")

    print("\nFacet coverage in final candidates:")
    for (facet_type, facet_value), count in facet_counts.most_common(20):
        print(f"  {facet_type}/{facet_value}: {count:,}")

    print(f"\nTop {min(show, total)} candidates:")
    for idx, candidate in enumerate(candidates[:show], start=1):
        facets = (
            f"{candidate.facet_type}/{candidate.facet_value}"
            if candidate.facet_type and candidate.facet_value
            else "-"
        )
        buckets = ",".join(sorted(candidate.buckets))
        print(
            f"{idx:>4}. {candidate.id} | {candidate.year} | {candidate.citations:,} cit | "
            f"{candidate.type or '-'} | {facets} | {buckets} | {candidate.title[:110]}"
        )


def write_csv(path: Path, candidates: list[Candidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "rank",
                "paper_id",
                "score",
                "title",
                "year",
                "citations",
                "fwci",
                "doi",
                "type",
                "subfield",
                "topic",
                "has_abstract",
                "open_access",
                "facet_type",
                "facet_value",
                "buckets",
            ],
        )
        writer.writeheader()
        for rank, candidate in enumerate(candidates, start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "paper_id": candidate.id,
                    "score": round(candidate.score, 4),
                    "title": candidate.title,
                    "year": candidate.year,
                    "citations": candidate.citations,
                    "fwci": candidate.fwci,
                    "doi": candidate.doi,
                    "type": candidate.type,
                    "subfield": candidate.subfield,
                    "topic": candidate.topic,
                    "has_abstract": candidate.has_abstract,
                    "open_access": candidate.open_access,
                    "facet_type": candidate.facet_type,
                    "facet_value": candidate.facet_value,
                    "buckets": ",".join(sorted(candidate.buckets)),
                }
            )


async def main() -> None:
    args = parse_args()
    candidates = await fetch_candidates(args)
    print_summary(candidates, args.show)
    if args.csv:
        write_csv(args.csv, candidates)
        print(f"\nCSV written: {args.csv}")


if __name__ == "__main__":
    asyncio.run(main())
