"""Trending topics endpoint based on paper facets and publication-year growth."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.services.paper_facets import get_facet_emoji, slugify_facet

router = APIRouter(prefix="/trending", tags=["trending"])


@router.get("")
async def get_trending(
    limit: int = Query(20, ge=1, le=50),
    axis: str = Query("aboutness", pattern="^(aboutness|method|task|application)$"),
    db: AsyncSession = Depends(get_db),
):
    """Return trending facets based on refreshed summary data."""
    result = await db.execute(
        text("""
        SELECT
            facet_value,
            paper_count,
            total_citations,
            recent_papers,
            previous_papers,
            growth_pct
        FROM paper_facet_summary
        WHERE facet_type = :axis
          AND recent_papers > 0
        ORDER BY growth_pct DESC, paper_count DESC
        LIMIT :limit
        """),
        {"axis": axis, "limit": limit},
    )
    rows = result.fetchall()

    return [
        {
            "rank": idx + 1,
            "topic_id": f"{axis}:{slugify_facet(row.facet_value)}",
            "topic_name": row.facet_value,
            "researcher_count": int(row.paper_count or 0),
            "paper_count": int(row.paper_count or 0),
            "contributions": int(row.paper_count or 0),
            "total_citations": int(row.total_citations or 0),
            "dominant_axis": axis,
            "growth_pct": round(float(row.growth_pct or 0), 1),
            "emoji": get_facet_emoji(row.facet_value),
        }
        for idx, row in enumerate(rows)
    ]
