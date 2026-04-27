"""
공동저자 그래프 빌드 서비스.

각 연구자에 대해:
1. OpenAlex /authors/{id}?select=topics 로 topic IDs 조회
2. OpenAlex /works?filter=author.id:{id} 로 논문 목록 조회
   → 공동저자 ID 추출 → DB에 있는 연구자만 collaboration 저장

Collaboration 테이블: (researcher_a, researcher_b, paper_count)
  - researcher_a < researcher_b 항상 보장 (중복 방지)
"""

import asyncio
import logging
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.researcher import Researcher
from app.models.collaboration import Collaboration

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)

_graph_status: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "errors": 0,
    "last_error": None,
}


def get_graph_status() -> dict:
    return dict(_graph_status)


async def _get(client: "httpx.AsyncClient", url: str, params: dict) -> dict:
    """단순 GET 요청, 실패 시 빈 dict 반환."""
    try:
        resp = await client.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning("OpenAlex GET failed: %s", e)
    return {}


async def _fetch_topics(client: "httpx.AsyncClient", author_id: str) -> list[str]:
    """연구자의 topic ID 목록 (최대 10개) 반환."""
    data = await _get(
        client,
        f"https://api.openalex.org/authors/{author_id}",
        {"select": "id,topics", "mailto": settings.OPENALEX_EMAIL},
    )
    topics = data.get("topics", [])
    return [t["id"].split("/")[-1] for t in topics[:10] if t.get("id")]


async def _fetch_coauthors(
    client: "httpx.AsyncClient",
    author_id: str,
    db_ids: set[str],
    max_pages: int = 3,
) -> dict[str, int]:
    """
    연구자의 논문 목록에서 공동저자 ID와 공저 논문 수를 추출합니다.
    DB에 있는 연구자만 반환.
    """
    coauthor_counts: dict[str, int] = {}
    cursor = "*"

    for _ in range(max_pages):
        data = await _get(
            client,
            "https://api.openalex.org/works",
            {
                "filter": f"author.id:{author_id}",
                "select": "id,authorships",
                "per_page": "200",
                "cursor": cursor,
                "mailto": settings.OPENALEX_EMAIL,
            },
        )
        results = data.get("results", [])
        if not results:
            break

        for work in results:
            for auth in work.get("authorships", []):
                raw_id = auth.get("author", {}).get("id", "")
                if not raw_id:
                    continue
                cid = raw_id.split("/")[-1]
                if cid != author_id and cid in db_ids:
                    coauthor_counts[cid] = coauthor_counts.get(cid, 0) + 1

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        await asyncio.sleep(0.12)

    return coauthor_counts


async def build_collaboration_graph() -> None:
    """
    모든 연구자의 topics와 공동저자 관계를 구축합니다.
    백그라운드 태스크로 실행됩니다.
    """
    if _graph_status["running"]:
        return

    from app.db.database import AsyncSessionLocal  # 순환 import 방지

    _graph_status.update({"running": True, "done": 0, "errors": 0, "last_error": None})

    async with AsyncSessionLocal() as db:
        # 전체 연구자 ID 세트
        id_result = await db.execute(select(Researcher.id))
        db_ids: set[str] = {row[0] for row in id_result}

        # 전체 연구자 목록
        r_result = await db.execute(select(Researcher))
        researchers = list(r_result.scalars().all())
        _graph_status["total"] = len(researchers)

        async with httpx.AsyncClient() as client:
            for researcher in researchers:
                try:
                    # 1. topics 업데이트
                    topics = await _fetch_topics(client, researcher.id)
                    researcher.topics = topics if topics else researcher.topics
                    await asyncio.sleep(0.12)

                    # 2. 공동저자 조회
                    coauthor_counts = await _fetch_coauthors(
                        client, researcher.id, db_ids
                    )

                    # 3. Collaboration 저장 (a < b 보장)
                    for cid, count in coauthor_counts.items():
                        a, b = sorted([researcher.id, cid])
                        existing = await db.execute(
                            select(Collaboration).where(
                                Collaboration.researcher_a == a,
                                Collaboration.researcher_b == b,
                            )
                        )
                        collab = existing.scalar_one_or_none()
                        if collab:
                            # 양쪽에서 카운트하면 중복 집계 → max 사용
                            collab.paper_count = max(collab.paper_count, count)
                        else:
                            db.add(
                                Collaboration(
                                    researcher_a=a, researcher_b=b, paper_count=count
                                )
                            )

                    await db.commit()
                    _graph_status["done"] += 1

                except Exception as e:
                    _graph_status["errors"] += 1
                    _graph_status["last_error"] = str(e)
                    logger.error("Graph build error for %s: %s", researcher.id, e)
                    await db.rollback()
                    continue

    _graph_status["running"] = False
    logger.info(
        "Graph build complete: %d done, %d errors",
        _graph_status["done"],
        _graph_status["errors"],
    )
