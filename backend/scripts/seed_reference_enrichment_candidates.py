"""
Seed paper_enrichment_status with high-precision OpenAlex reference candidates.

The script is idempotent. Existing fetched rows are not reset to pending.

Usage:
    cd backend
    .venv/bin/python -m scripts.seed_reference_enrichment_candidates --limit 1000
    .venv/bin/python -m scripts.seed_reference_enrichment_candidates --limit 30000 --include-preprints --allow-missing-abstract
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.database import AsyncSessionLocal
from scripts.select_reference_enrichment_candidates import fetch_candidates, parse_args


SOURCE = "openalex"

UPSERT_SQL = text("""
INSERT INTO paper_enrichment_status (
    paper_id,
    source,
    status,
    candidate_bucket,
    candidate_score,
    updated_at
)
VALUES (
    :paper_id,
    :source,
    'pending',
    :candidate_bucket,
    :candidate_score,
    now()
)
ON CONFLICT (paper_id, source) DO UPDATE SET
    candidate_bucket = EXCLUDED.candidate_bucket,
    candidate_score = GREATEST(
        COALESCE(paper_enrichment_status.candidate_score, 0),
        COALESCE(EXCLUDED.candidate_score, 0)
    ),
    status = CASE
        WHEN paper_enrichment_status.status IN ('fetched', 'in_progress')
            THEN paper_enrichment_status.status
        ELSE 'pending'
    END,
    error = CASE
        WHEN paper_enrichment_status.status IN ('fetched', 'in_progress')
            THEN paper_enrichment_status.error
        ELSE NULL
    END,
    updated_at = now()
""")

SUMMARY_SQL = text("""
SELECT status, COUNT(*) AS n
FROM paper_enrichment_status
WHERE source = :source
GROUP BY status
ORDER BY status
""")


async def main() -> None:
    args = parse_args()
    candidates = await fetch_candidates(args)
    print(f"seeding candidates: {len(candidates):,}", flush=True)

    async with AsyncSessionLocal() as db:
        for candidate in candidates:
            await db.execute(
                UPSERT_SQL,
                {
                    "paper_id": candidate.id,
                    "source": SOURCE,
                    "candidate_bucket": ",".join(sorted(candidate.buckets)),
                    "candidate_score": candidate.score,
                },
            )
        await db.commit()

        rows = (await db.execute(SUMMARY_SQL, {"source": SOURCE})).fetchall()

    print("paper_enrichment_status:")
    for row in rows:
        print(f"  {row.status}: {int(row.n):,}")


if __name__ == "__main__":
    asyncio.run(main())
