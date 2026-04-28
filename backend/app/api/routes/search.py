"""Universal search endpoint — parse intent and return routing info."""

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.db.database import get_db
from app.models.researcher import Researcher
from app.services.query_parser import parse_query
from app.services.paper_facets import canonicalize_facet_query

router = APIRouter(prefix="/search", tags=["search"])

COUNTRY_QUERY_ALIASES = {
    "한국": "KR",
    "대한민국": "KR",
    "korea": "KR",
    "south korea": "KR",
    "미국": "US",
    "usa": "US",
    "us": "US",
    "united states": "US",
    "중국": "CN",
    "china": "CN",
    "일본": "JP",
    "japan": "JP",
}

TOPIC_QUERY_ALIASES = {
    "디퓨전": "diffusion",
    "diffusion": "diffusion",
    "확산모델": "diffusion",
    "확산 모델": "diffusion",
    "트랜스포머": "transformer",
    "transformer": "transformer",
    "llm": "LLM",
    "대규모 언어 모델": "LLM",
    "rag": "RAG",
    "검색증강": "RAG",
}

TREND_QUERY_TERMS = ("추이", "흐름", "성장", "변화", "트렌드", "trend", "progress", "growth")


async def _topic_paper_count(db: AsyncSession, topic: str) -> tuple[str, int]:
    canonical, matched_axes = canonicalize_facet_query(topic)
    result = await db.execute(
        text("""
        SELECT COALESCE(SUM(paper_count), 0) AS paper_count
        FROM paper_facet_summary
        WHERE lower(facet_value) = lower(:facet_value)
          AND (:use_axes = false OR facet_type = ANY(:axes))
        """),
        {
            "facet_value": canonical,
            "use_axes": bool(matched_axes),
            "axes": matched_axes or ["aboutness", "method", "task", "application"],
        },
    )
    return canonical, int(result.scalar_one() or 0)


def _parse_country_topic_trend(q: str) -> dict[str, str] | None:
    normalized = q.strip().lower()
    if not any(term in normalized for term in TREND_QUERY_TERMS):
        return None

    countries: list[str] = []
    for alias, code in COUNTRY_QUERY_ALIASES.items():
        if alias.isascii():
            matched = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized) is not None
        else:
            matched = alias in normalized
        if matched and code not in countries:
            countries.append(code)

    topic = None
    for alias, canonical in TOPIC_QUERY_ALIASES.items():
        if alias.isascii():
            matched = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized) is not None
        else:
            matched = alias in normalized
        if matched:
            topic = canonical
            break

    if len(countries) >= 2 and topic:
        return {
            "type": "country",
            "entities": ",".join(countries[:3]),
            "topic": topic,
        }
    return None


@router.get("/universal")
async def universal_search(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """
    Parse a natural language query and return:
    - intent: researcher_search | topic_map | benchmark | stats
    - params: structured params for the destination page
    - explanation: human-readable (same language as query)
    - answer: direct answer for stats queries
    """
    normalized_q = q.strip().lower()
    country_topic_trend = _parse_country_topic_trend(q)
    if country_topic_trend:
        return {
            "intent": "progress",
            "params": country_topic_trend,
            "explanation": "국가별 세부 토픽 논문 추이를 비교합니다.",
            "redirect": "/progress",
            "answer": None,
            "answer_label": None,
        }

    if normalized_q.endswith(" papers"):
        topic = q.strip()[:-len(" papers")].strip()
        if topic:
            canonical, count = await _topic_paper_count(db, topic)
            return {
                "intent": "stats",
                "params": {},
                "explanation": f"{canonical} 관련 논문 수를 조회합니다.",
                "redirect": None,
                "answer": count,
                "answer_label": f"'{canonical}' 관련 논문",
            }

    parsed = await parse_query(q)
    intent = parsed.get("intent", "topic_map")

    # ── Comparison: return type + entities for frontend to fetch ────────────
    if intent == "comparison":
        return {
            "intent": "comparison",
            "params": {
                "comparison_type": parsed.get("comparison_type", "country"),
                "entities": ",".join(parsed.get("entities", [])),
            },
            "explanation": parsed.get("explanation", ""),
            "redirect": None,
            "answer": None,
        }

    # ── Stats: return count directly, no navigation ──────────────────────────
    if intent == "stats":
        field   = parsed.get("field")
        country = parsed.get("country")
        topic   = parsed.get("topic")

        count: int | None = None

        if field or country:
            # Count from our DB
            stmt = select(func.count()).select_from(Researcher)
            if field:
                stmt = stmt.where(Researcher.field == field)
            if country:
                stmt = stmt.where(Researcher.country == country)
            count = await db.scalar(stmt) or 0

        elif topic:
            canonical, count = await _topic_paper_count(db, topic)

        return {
            "intent": "stats",
            "params": {},
            "explanation": parsed.get("explanation", ""),
            "redirect": None,
            "answer": count,
            "answer_label": (
                f"{field} 분야 연구자" if field else
                f"{country} 연구자" if country else
                f"'{topic}' 관련 논문"
            ),
        }

    # ── Trending ───────────────────────────────────────────────────────────────
    if intent == "trending":
        return {
            "intent": "trending",
            "params": {},
            "explanation": parsed.get("explanation", ""),
            "redirect": "/trending",
            "answer": None,
            "answer_label": None,
        }

    # ── Progress ──────────────────────────────────────────────────────────────
    if intent == "progress":
        progress_params = {
            "type": parsed.get("progress_type", "country"),
            "entity": parsed.get("entity", ""),
        }
        if parsed.get("entities"):
            progress_params["entities"] = ",".join(parsed.get("entities", [])[:3])
            progress_params.pop("entity", None)
        if parsed.get("topic"):
            progress_params["topic"] = parsed.get("topic")
        return {
            "intent": "progress",
            "params": progress_params,
            "explanation": parsed.get("explanation", ""),
            "redirect": "/progress",
            "answer": None,
            "answer_label": None,
        }

    # ── Leaderboard ───────────────────────────────────────────────────────────
    if intent == "leaderboard":
        return {
            "intent": "leaderboard",
            "params": {"type": parsed.get("leaderboard_type", "country")},
            "explanation": parsed.get("explanation", ""),
            "redirect": "/leaderboard",
            "answer": None,
            "answer_label": None,
        }

    # ── Researcher DNA ────────────────────────────────────────────────────────
    if intent == "researcher_dna":
        name = parsed.get("name", "")
        # Try to find researcher by name
        if name:
            stmt = (
                select(Researcher)
                .where(func.lower(Researcher.name).contains(name.lower()))
                .order_by(Researcher.citations.desc())
                .limit(1)
            )
            r = await db.execute(stmt)
            researcher = r.scalar_one_or_none()
            if researcher:
                return {
                    "intent": "researcher_dna",
                    "params": {"id": researcher.id},
                    "explanation": parsed.get("explanation", ""),
                    "redirect": f"/researcher/{researcher.id}",
                    "answer": None,
                    "answer_label": None,
                }
        return {
            "intent": "researcher_dna",
            "params": {"name": name},
            "explanation": parsed.get("explanation", "연구자를 찾을 수 없습니다."),
            "redirect": None,
            "answer": None,
            "answer_label": None,
        }

    # ── Researcher search → Globe ─────────────────────────────────────────────
    if intent == "researcher_search":
        params = {k: v for k, v in parsed.items()
                  if k in ("field", "country", "city", "institution", "topic", "sort") and v}
        return {
            "intent": intent,
            "params": params,
            "explanation": parsed.get("explanation", ""),
            "redirect": "/",
            "answer": None,
        }

    # ── Topic map ─────────────────────────────────────────────────────────────
    if intent == "topic_map":
        return {
            "intent": intent,
            "params": {"query": parsed.get("query", q)},
            "explanation": parsed.get("explanation", ""),
            "redirect": "/map",
            "answer": None,
        }

    # ── Benchmark ─────────────────────────────────────────────────────────────
    return {
        "intent": intent,
        "params": {"query": parsed.get("query", q)},
        "explanation": parsed.get("explanation", ""),
        "redirect": "/benchmarks",
        "answer": None,
    }
