"""
OpenAlex 토픽 이름 매핑 파일 생성 스크립트.

DB의 researchers.topics 배열에서 고유 topic ID를 추출하고
OpenAlex API에서 이름을 가져와 backend/data/topic_names.json에 저장합니다.

Usage:
    cd backend
    .venv/bin/python -m scripts.fetch_topic_names
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import AsyncSessionLocal
from app.models.researcher import Researcher
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "topic_names.json"
OA_TOPICS_URL = "https://api.openalex.org/topics"
BATCH_SIZE = 50
SLEEP_BETWEEN = 0.2


async def collect_topic_ids() -> list[str]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Researcher.topics).where(Researcher.topics.isnot(None))
        )
        all_ids: set[str] = set()
        for (topics,) in result:
            if topics:
                all_ids.update(topics)
        return sorted(all_ids)


async def fetch_all_topics(client: httpx.AsyncClient) -> dict[str, str]:
    """OpenAlex 전체 topics 목록을 cursor 페이지네이션으로 가져옵니다."""
    mapping: dict[str, str] = {}
    cursor = "*"
    page = 0
    while cursor:
        retry = 0
        while retry < 5:
            try:
                r = await client.get(
                    OA_TOPICS_URL,
                    params={"per_page": 200, "cursor": cursor, "select": "id,display_name"},
                    timeout=20,
                )
                if r.status_code == 429:
                    wait = 2 ** retry * 3
                    logger.warning(f"429 rate limit — waiting {wait}s")
                    await asyncio.sleep(wait)
                    retry += 1
                    continue
                r.raise_for_status()
                data = r.json()
                results = data.get("results", [])
                for item in results:
                    if "id" in item and "display_name" in item:
                        tid = item["id"].split("/")[-1]  # "https://openalex.org/T10028" → "T10028"
                        mapping[tid] = item["display_name"]
                cursor = data.get("meta", {}).get("next_cursor")
                page += 1
                logger.info(f"Page {page}: fetched {len(results)} topics (total so far: {len(mapping)})")
                if cursor:
                    await asyncio.sleep(SLEEP_BETWEEN)
                break
            except Exception as e:
                logger.warning(f"Page {page} failed: {e}")
                break
    return mapping


async def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing mapping
    existing: dict[str, str] = {}
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text())
        except Exception:
            pass
        if len(existing) > 100:
            logger.info(f"Loaded {len(existing)} existing topic names — skipping fetch")
            return

    logger.info("Fetching all topics from OpenAlex (cursor pagination)...")
    async with httpx.AsyncClient(headers={"User-Agent": "ResearcherHub/1.0 (mailto:research@example.com)"}) as client:
        mapping = await fetch_all_topics(client)

    OUTPUT_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    logger.info(f"Saved {len(mapping)} topic names to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
