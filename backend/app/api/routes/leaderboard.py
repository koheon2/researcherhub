"""Leaderboard endpoint — country / institution / researcher rankings."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import distinct, exists, select, func, text
from app.db.database import get_db
from app.models.paper import Paper, PaperAuthorAffiliation, PaperQualityFlag
from app.models.researcher import Researcher

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

QUALITY_PROVENANCE = {
    "quality_filtered": True,
    "quality_policy": "conservative_v0",
}

FIELD_TO_SUBFIELD: dict[str, str] = {
    "AI": "Artificial Intelligence",
    "Computer Vision": "Computer Vision and Pattern Recognition",
    "NLP": "Natural Language Processing",
    "HCI": "Human-Computer Interaction",
    "Theory & Math": "Computational Theory and Mathematics",
    "Information Systems": "Information Systems",
    "Software Engineering": "Software Engineering",
    "Networks": "Computer Networks and Communications",
    "Hardware": "Hardware and Architecture",
    "Signal Processing": "Signal Processing",
    "Robotics": "Robotics",
    "Computer Science": "General Computer Science",
}


def _paper_subfield(field: str | None) -> str | None:
    if not field:
        return None
    return FIELD_TO_SUBFIELD.get(field, field)


@router.get("")
async def get_leaderboard(
    type: str = Query("country", description="country | institution | researcher"),
    field: str | None = Query(None, description="Filter by field"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    if type == "country":
        return await _country_leaderboard(db, field, limit)
    elif type == "institution":
        return await _institution_leaderboard(db, field, limit)
    else:
        return await _researcher_leaderboard(db, field, limit)


async def _country_leaderboard(db: AsyncSession, field: str | None, limit: int):
    subfield = _paper_subfield(field)
    if not subfield:
        result = await db.execute(
            text("""
            SELECT country_code AS country, contributions, papers, total_citations
            FROM publication_country_stats
            ORDER BY contributions DESC
            LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.fetchall()
        return {
            "type": "country",
            "field": field,
            "entries": [
                {
                    "rank": i + 1,
                    "key": r.country,
                    "name": r.country,
                    "researcher_count": r.contributions,
                    "contributions": r.contributions,
                    "papers": r.papers,
                    "total_citations": int(r.total_citations or 0),
                    "avg_h_index": 0,
                }
                for i, r in enumerate(rows)
            ],
            **QUALITY_PROVENANCE,
        }

    base = select(
        PaperAuthorAffiliation.country_code.label("country"),
        func.count(PaperAuthorAffiliation.id).label("contributions"),
        func.count(distinct(PaperAuthorAffiliation.paper_id)).label("papers"),
        func.sum(Paper.citations).label("total_citations"),
    ).join(Paper, Paper.id == PaperAuthorAffiliation.paper_id).where(
        PaperAuthorAffiliation.country_code.isnot(None)
    )

    if subfield:
        base = base.where(Paper.subfield == subfield)

    base = base.where(
        ~exists()
        .where(PaperQualityFlag.paper_id == Paper.id)
        .where(PaperQualityFlag.severity == "exclude")
    )

    result = await db.execute(
        base.group_by(PaperAuthorAffiliation.country_code)
        .order_by(func.count(PaperAuthorAffiliation.id).desc())
        .limit(limit)
    )
    rows = result.fetchall()
    return {
        "type": "country",
        "field": field,
        "entries": [
            {
                "rank": i + 1,
                "key": r.country,
                "name": r.country,
                "researcher_count": r.contributions,
                "contributions": r.contributions,
                "papers": r.papers,
                "total_citations": int(r.total_citations or 0),
                "avg_h_index": 0,
            }
            for i, r in enumerate(rows)
        ],
        **QUALITY_PROVENANCE,
    }


async def _institution_leaderboard(db: AsyncSession, field: str | None, limit: int):
    subfield = _paper_subfield(field)
    if not subfield:
        result = await db.execute(
            text("""
            SELECT institution_name AS institution, contributions, papers, total_citations
            FROM publication_institution_stats
            ORDER BY contributions DESC
            LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.fetchall()
        return {
            "type": "institution",
            "field": field,
            "entries": [
                {
                    "rank": i + 1,
                    "key": r.institution,
                    "name": r.institution,
                    "researcher_count": r.contributions,
                    "contributions": r.contributions,
                    "papers": r.papers,
                    "total_citations": int(r.total_citations or 0),
                    "avg_h_index": 0,
                }
                for i, r in enumerate(rows)
            ],
            **QUALITY_PROVENANCE,
        }

    result = await db.execute(
        text("""
        WITH excluded AS (
            SELECT DISTINCT paper_id
            FROM paper_quality_flags
            WHERE severity = 'exclude'
        )
        SELECT
            CASE
                WHEN inm.status = 'matched' AND inm.canonical_name IS NOT NULL
                    THEN inm.canonical_name
                ELSE paa.institution_name
            END AS institution,
            COUNT(*)::bigint AS contributions,
            COUNT(DISTINCT paa.paper_id)::bigint AS papers,
            COALESCE(SUM(p.citations), 0)::bigint AS total_citations
        FROM paper_author_affiliations paa
        JOIN papers p ON p.id = paa.paper_id
        LEFT JOIN excluded e ON e.paper_id = p.id
        LEFT JOIN institution_name_matches inm
          ON inm.raw_institution_name = paa.institution_name
         AND inm.country_code = paa.country_code
        WHERE paa.institution_name IS NOT NULL
          AND paa.institution_name <> ''
          AND e.paper_id IS NULL
          AND p.subfield = :subfield
        GROUP BY
            CASE
                WHEN inm.status = 'matched' AND inm.canonical_name IS NOT NULL
                    THEN inm.canonical_name
                ELSE paa.institution_name
            END
        ORDER BY COUNT(*) DESC
        LIMIT :limit
        """),
        {"subfield": subfield, "limit": limit},
    )
    rows = result.fetchall()
    return {
        "type": "institution",
        "field": field,
        "entries": [
            {
                "rank": i + 1,
                "key": r.institution,
                "name": r.institution,
                "researcher_count": r.contributions,
                "contributions": r.contributions,
                "papers": r.papers,
                "total_citations": int(r.total_citations or 0),
                "avg_h_index": 0,
            }
            for i, r in enumerate(rows)
        ],
        **QUALITY_PROVENANCE,
    }


async def _researcher_leaderboard(db: AsyncSession, field: str | None, limit: int):
    base = select(Researcher)

    if field:
        base = base.where(Researcher.field == field)

    result = await db.execute(
        base.order_by(Researcher.citations.desc()).limit(limit)
    )
    researchers = result.scalars().all()
    return {
        "type": "researcher",
        "field": field,
        "entries": [
            {
                "rank": i + 1,
                "key": r.id,
                "name": r.name,
                "institution": r.institution,
                "country": r.country,
                "field": r.field,
                "citations": r.citations,
                "h_index": r.h_index,
                "works_count": r.works_count,
            }
            for i, r in enumerate(researchers)
        ],
    }
