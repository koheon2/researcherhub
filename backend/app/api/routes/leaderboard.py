"""Leaderboard endpoint — country / institution / researcher rankings."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import distinct, exists, select, func, text
from app.db.database import get_db
from app.models.paper import Paper, PaperAuthorAffiliation, PaperQualityFlag
from app.models.researcher import Researcher
from app.services.paper_facets import canonicalize_facet_query

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
    type: str = Query("country", description="country | institution | researcher | author"),
    field: str | None = Query(None, description="Filter by field"),
    country: str | None = Query(None, description="Publication-time country filter for author rankings"),
    topic: str | None = Query(None, description="Facet filter for author rankings"),
    year_start: int | None = Query(None, ge=1900, le=2100),
    year_end: int | None = Query(None, ge=1900, le=2100),
    sort: str = Query("citations", description="citations | contributions | papers | hotness"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    if type == "country":
        return await _country_leaderboard(db, field, limit)
    elif type == "institution":
        return await _institution_leaderboard(db, field, limit)
    elif type == "author":
        return await _author_leaderboard(db, country, topic, year_start, year_end, sort, limit)
    elif country or topic or year_start or year_end or sort in {"contributions", "papers", "hotness"}:
        return await _author_leaderboard(db, country, topic, year_start, year_end, sort, limit)
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
            WITH metadata AS (
                SELECT
                    canonical_name,
                    MAX(institution_ror_id) FILTER (
                        WHERE institution_ror_id IS NOT NULL
                          AND institution_ror_id <> ''
                    ) AS institution_ror_id,
                    MAX(confidence) AS institution_match_confidence
                FROM institution_name_matches
                WHERE status = 'matched'
                  AND canonical_name IS NOT NULL
                  AND canonical_name <> ''
                GROUP BY canonical_name
            )
            SELECT
                stats.institution_name AS institution,
                stats.contributions,
                stats.papers,
                stats.total_citations,
                metadata.institution_ror_id,
                metadata.institution_match_confidence,
                (metadata.canonical_name IS NOT NULL) AS institution_normalized
            FROM publication_institution_stats stats
            LEFT JOIN metadata ON metadata.canonical_name = stats.institution_name
            ORDER BY stats.contributions DESC
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
                    "institution_ror_id": r.institution_ror_id,
                    "institution_match_confidence": round(float(r.institution_match_confidence), 3)
                    if r.institution_match_confidence is not None else None,
                    "institution_normalized": bool(r.institution_normalized),
                }
                for i, r in enumerate(rows)
            ],
            **QUALITY_PROVENANCE,
        }

    result = await db.execute(
        text("""
        SELECT
            institution_name AS institution,
            contributions,
            papers,
            total_citations,
            institution_ror_id,
            institution_match_confidence,
            institution_normalized
        FROM publication_institution_field_stats
        WHERE subfield = :subfield
        ORDER BY contributions DESC
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
                "institution_ror_id": r.institution_ror_id,
                "institution_match_confidence": round(float(r.institution_match_confidence), 3)
                if r.institution_match_confidence is not None else None,
                "institution_normalized": bool(r.institution_normalized),
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


async def _author_leaderboard(
    db: AsyncSession,
    country: str | None,
    topic: str | None,
    year_start: int | None,
    year_end: int | None,
    sort: str,
    limit: int,
) -> dict:
    current_year = int(await db.scalar(text("SELECT EXTRACT(YEAR FROM CURRENT_DATE)::int")) or 2026)
    end_year = year_end or current_year
    if year_start is not None:
        start_year = year_start
    elif sort == "hotness":
        start_year = max(1900, end_year - 2)
    else:
        start_year = 2017
    if start_year > end_year:
        start_year, end_year = end_year, start_year

    canonical_topic = None
    axes = ["aboutness", "method", "task", "application"]
    if topic:
        canonical_topic, matched_axes = canonicalize_facet_query(topic)
        axes = matched_axes or axes

    sort_expr = {
        "contributions": "contributions DESC, total_citations DESC",
        "papers": "papers DESC, total_citations DESC",
        "hotness": "hotness_score DESC, recent_contributions DESC, total_citations DESC",
        "citations": "total_citations DESC, contributions DESC",
    }.get(sort, "total_citations DESC, contributions DESC")

    topic_cte = """
        WITH matched_papers AS MATERIALIZED (
            SELECT DISTINCT paper_id
            FROM paper_facets
            WHERE facet_value = CAST(:topic AS text)
              AND facet_type = ANY(CAST(:axes AS text[]))
        ),
        base AS (
    """ if canonical_topic else "WITH base AS ("
    topic_join = "JOIN matched_papers mp ON mp.paper_id = paa.paper_id" if canonical_topic else ""

    result = await db.execute(
        text(f"""
        {topic_cte}
            SELECT
                paa.author_id,
                MAX(paa.author_name) AS author_name,
                MAX(paa.institution_name) AS institution_name,
                MAX(paa.country_code) AS country_code,
                COUNT(*)::bigint AS contributions,
                COUNT(DISTINCT paa.paper_id)::bigint AS papers,
                COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
                COALESCE(AVG(p.citations), 0)::float AS avg_paper_citations,
                COUNT(*) FILTER (
                    WHERE paa.publication_year >= :end_year - 2
                )::bigint AS recent_contributions,
                MIN(paa.publication_year) AS min_year,
                MAX(paa.publication_year) AS max_year
            FROM paper_author_affiliations paa
            JOIN papers p ON p.id = paa.paper_id
            {topic_join}
            WHERE paa.author_id IS NOT NULL
              AND paa.author_id <> ''
              AND paa.publication_year >= :start_year
              AND paa.publication_year <= :end_year
              AND (CAST(:country AS text) IS NULL OR paa.country_code = CAST(:country AS text))
              AND NOT EXISTS (
                  SELECT 1
                  FROM paper_quality_flags pqf
                  WHERE pqf.paper_id = paa.paper_id
                    AND pqf.severity = 'exclude'
              )
            GROUP BY paa.author_id
        )
        SELECT
            *,
            (
                recent_contributions * 10
                + LEAST(total_citations, 5000)::float / 100
                + papers * 2
            ) AS hotness_score
        FROM base
        ORDER BY {sort_expr}
        LIMIT :limit
        """),
        {
            "country": country.upper() if country else None,
            "topic": canonical_topic,
            "axes": axes,
            "start_year": start_year,
            "end_year": end_year,
            "limit": limit,
        },
    )
    rows = result.fetchall()
    return {
        "type": "author",
        "field": None,
        "country": country.upper() if country else None,
        "topic": canonical_topic,
        "year_start": start_year,
        "year_end": end_year,
        "sort": sort,
        "entries": [
            {
                "rank": i + 1,
                "key": r.author_id,
                "name": r.author_name or r.author_id,
                "institution": r.institution_name,
                "country": r.country_code,
                "citations": int(r.total_citations or 0),
                "h_index": 0,
                "works_count": int(r.papers or 0),
                "contributions": int(r.contributions or 0),
                "papers": int(r.papers or 0),
                "total_citations": int(r.total_citations or 0),
                "avg_paper_citations": round(float(r.avg_paper_citations or 0), 1),
                "recent_contributions": int(r.recent_contributions or 0),
                "hotness_score": round(float(r.hotness_score or 0), 1),
                "min_year": int(r.min_year) if r.min_year is not None else None,
                "max_year": int(r.max_year) if r.max_year is not None else None,
            }
            for i, r in enumerate(rows)
        ],
        **QUALITY_PROVENANCE,
    }
