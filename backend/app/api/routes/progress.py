"""Progress endpoint — year-over-year trend endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import distinct, select, func, text
from app.db.database import get_db
from app.models.paper import Paper, PaperAuthorAffiliation, PaperFacet
from app.models.researcher import Researcher
from app.services.paper_facets import canonicalize_facet_query

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("")
async def get_progress(
    type: str = Query("country", description="country | field"),
    entity: str = Query(..., description="Country code (e.g. KR) or field name (e.g. AI)"),
    years: int = Query(10, ge=3, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Return year-over-year trend for a country or field."""
    if type == "country":
        return await _country_progress(db, entity.upper(), years)

    return await _field_progress(db, entity, years)


async def _country_progress(db: AsyncSession, entity: str, years: int) -> dict:
    max_year = await db.scalar(
        select(func.max(PaperAuthorAffiliation.publication_year))
        .where(PaperAuthorAffiliation.country_code == entity)
    )
    if max_year is None:
        return {
            "type": "country",
            "entity": entity,
            "trend": [],
            "current": {"researcher_count": 0, "avg_citations": 0, "contributions": 0},
        }

    start_year = int(max_year) - years + 1
    result = await db.execute(
        select(
            PaperAuthorAffiliation.publication_year.label("year"),
            func.count(PaperAuthorAffiliation.id).label("contributions"),
            func.coalesce(func.avg(Paper.citations), 0).label("avg_cit"),
        )
        .join(Paper, Paper.id == PaperAuthorAffiliation.paper_id)
        .where(PaperAuthorAffiliation.country_code == entity)
        .where(PaperAuthorAffiliation.publication_year >= start_year)
        .where(PaperAuthorAffiliation.publication_year <= max_year)
        .group_by(PaperAuthorAffiliation.publication_year)
        .order_by(PaperAuthorAffiliation.publication_year)
    )
    by_year = {
        int(r.year): {
            "researcher_count": int(r.contributions or 0),
            "contributions": int(r.contributions or 0),
            "avg_citations": round(float(r.avg_cit or 0), 1),
        }
        for r in result.fetchall()
    }

    trend = []
    for year in range(start_year, int(max_year) + 1):
        row = by_year.get(year, {"researcher_count": 0, "contributions": 0, "avg_citations": 0})
        trend.append({"year": year, **row})

    total_contributions = sum(p["contributions"] for p in trend)
    weighted_citations = sum(p["avg_citations"] * p["contributions"] for p in trend)
    avg_citations = round(weighted_citations / total_contributions, 1) if total_contributions else 0

    return {
        "type": "country",
        "entity": entity,
        "trend": [p for p in trend if p["contributions"] > 0],
        "current": {
            "researcher_count": total_contributions,
            "contributions": total_contributions,
            "avg_citations": avg_citations,
        },
    }


async def _field_progress(db: AsyncSession, entity: str, years: int) -> dict:
    canonical, matched_axes = canonicalize_facet_query(entity)
    axis_filter = matched_axes or ["aboutness", "method", "task", "application"]
    max_year = await db.scalar(
        text("""
        SELECT MAX(year)
        FROM paper_facet_year_summary
        WHERE lower(facet_value) = lower(:facet_value)
          AND facet_type = ANY(:axes)
        """),
        {"facet_value": canonical, "axes": axis_filter},
    )
    if max_year is None:
        return {
            "type": "field",
            "entity": entity,
            "trend": [],
            "current": {"researcher_count": 0, "contributions": 0, "avg_citations": 0},
        }

    start_year = int(max_year) - years + 1
    result = await db.execute(
        text("""
        SELECT
            year,
            SUM(paper_count)::bigint AS paper_count,
            SUM(total_citations)::bigint AS total_citations
        FROM paper_facet_year_summary
        WHERE lower(facet_value) = lower(:facet_value)
          AND facet_type = ANY(:axes)
          AND year >= :start_year
          AND year <= :max_year
        GROUP BY year
        ORDER BY year
        """),
        {
            "facet_value": canonical,
            "axes": axis_filter,
            "start_year": start_year,
            "max_year": int(max_year),
        },
    )
    by_year = {
        int(r.year): {
            "researcher_count": int(r.paper_count or 0),
            "papers": int(r.paper_count or 0),
            "contributions": int(r.paper_count or 0),
            "avg_citations": round((int(r.total_citations or 0) / int(r.paper_count or 1)), 1),
        }
        for r in result.fetchall()
    }

    trend = []
    for year in range(start_year, int(max_year) + 1):
        row = by_year.get(year, {"researcher_count": 0, "papers": 0, "contributions": 0, "avg_citations": 0})
        trend.append({"year": year, **row})

    total_papers = sum(p["papers"] for p in trend)
    total_contributions = sum(p["contributions"] for p in trend)
    weighted_citations = sum(p["avg_citations"] * p["papers"] for p in trend)
    avg_citations = round(weighted_citations / total_papers, 1) if total_papers else 0
    return {
        "type": "field",
        "entity": canonical,
        "trend": [p for p in trend if p["papers"] > 0],
        "current": {
            "researcher_count": total_papers,
            "contributions": total_contributions,
            "avg_citations": avg_citations,
        },
    }
