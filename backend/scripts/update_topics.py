"""
기존 연구자들의 topics를 업데이트하는 스크립트.

두 가지 모드:
  --mode api   (기본) OpenAlex API로 배치 조회 (빠름, ~50개씩 pipe-or 필터)
  --mode s3    S3 스냅샷 전체 스트리밍 (느리지만 API 제한 없음)

Usage:
    cd backend
    .venv/bin/python -m scripts.update_topics           # API 모드
    .venv/bin/python -m scripts.update_topics --mode s3  # S3 모드
"""

import argparse
import asyncio
import gzip
import json
import logging
import sys
import time
from pathlib import Path

# backend 디렉토리를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import AsyncSessionLocal
from app.models.researcher import Researcher
from app.core.config import settings
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def get_null_topic_ids() -> list[str]:
    """DB에서 topics가 null인 연구자 ID 목록을 가져옵니다."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Researcher.id).where(Researcher.topics.is_(None))
        )
        ids = [row[0] for row in result]
        logger.info(f"Found {len(ids)} researchers with null topics")
        return ids


async def update_topics_batch(updates: dict[str, list[str]]) -> int:
    """topics를 배치로 DB에 업데이트합니다. topics 컬럼만 변경합니다."""
    from sqlalchemy import update
    count = 0
    async with AsyncSessionLocal() as db:
        for researcher_id, topic_ids in updates.items():
            result = await db.execute(
                update(Researcher)
                .where(Researcher.id == researcher_id)
                .values(topics=topic_ids)
            )
            if result.rowcount > 0:
                count += 1
        await db.commit()
    return count


# ── API 모드 ──────────────────────────────────────────────────────────────────

async def run_api_mode(target_ids: list[str]):
    """OpenAlex API로 배치 조회하여 topics를 업데이트합니다."""
    try:
        import httpx
    except ImportError:
        logger.error("httpx not installed. Run: pip install httpx")
        return

    BATCH_SIZE = 50  # OpenAlex pipe-or 필터 최대 ~50개
    total_updated = 0
    total_not_found = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for start in range(0, len(target_ids), BATCH_SIZE):
            batch_ids = target_ids[start : start + BATCH_SIZE]
            # OpenAlex pipe-or 필터: author.id:A123|A456|...
            openalex_ids = "|".join(
                f"https://openalex.org/A{aid}" if not aid.startswith("A") else f"https://openalex.org/{aid}"
                for aid in batch_ids
            )

            try:
                resp = await client.get(
                    "https://api.openalex.org/authors",
                    params={
                        "filter": f"openalex:{openalex_ids}",
                        "select": "id,topics",
                        "per_page": str(len(batch_ids)),
                        "mailto": settings.OPENALEX_EMAIL,
                    },
                )
                if resp.status_code == 429:
                    logger.warning("Rate limited, waiting 3s...")
                    await asyncio.sleep(3.0)
                    continue

                if resp.status_code != 200:
                    logger.warning(f"API error {resp.status_code}: {resp.text[:200]}")
                    await asyncio.sleep(1.0)
                    continue

                data = resp.json()
                results = data.get("results", [])

                updates: dict[str, list[str]] = {}
                for author in results:
                    aid = author.get("id", "").split("/")[-1]
                    raw_topics = author.get("topics") or []
                    topic_ids_list = [
                        t.get("id", "").split("/")[-1]
                        for t in raw_topics[:5]
                        if t.get("id")
                    ]
                    if topic_ids_list:
                        updates[aid] = topic_ids_list

                if updates:
                    count = await update_topics_batch(updates)
                    total_updated += count

                total_not_found += len(batch_ids) - len(results)

            except Exception as e:
                logger.warning(f"Batch error at offset {start}: {e}")
                await asyncio.sleep(1.0)
                continue

            # 진행상황 출력 (1000명마다)
            processed = start + len(batch_ids)
            if processed % 1000 < BATCH_SIZE or processed >= len(target_ids):
                logger.info(
                    f"Progress: {processed}/{len(target_ids)} "
                    f"({total_updated} updated, {total_not_found} not found)"
                )

            # polite pool 딜레이
            await asyncio.sleep(0.12)

    logger.info(f"API mode done: {total_updated} updated, {total_not_found} not found in API")


# ── S3 모드 ──────────────────────────────────────────────────────────────────

async def run_s3_mode(target_ids: list[str]):
    """S3 스냅샷에서 스트리밍하면서 topics를 업데이트합니다."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    BUCKET = "openalex"
    AUTHORS_PREFIX = "data/authors/"

    s3 = boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED))
    target_set = set(target_ids)

    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=AUTHORS_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".gz"):
                keys.append(obj["Key"])

    logger.info(f"Total S3 author files: {len(keys)}")

    batch: dict[str, list[str]] = {}
    total_found = 0
    DB_BATCH = 200

    for file_idx, key in enumerate(keys):
        try:
            resp = s3.get_object(Bucket=BUCKET, Key=key)
            with gzip.GzipFile(fileobj=resp["Body"]) as gz:
                for line_bytes in gz:
                    try:
                        record = json.loads(line_bytes)
                    except json.JSONDecodeError:
                        continue

                    author_id = record.get("id", "").split("/")[-1]
                    if author_id not in target_set:
                        continue

                    raw_topics = record.get("topics") or []
                    topic_ids_list = [
                        t.get("id", "").split("/")[-1]
                        for t in raw_topics[:5]
                        if t.get("id")
                    ]
                    if topic_ids_list:
                        batch[author_id] = topic_ids_list
                        total_found += 1

                        if len(batch) >= DB_BATCH:
                            updated = await update_topics_batch(batch)
                            logger.info(f"Updated {updated} ({total_found} found)")
                            batch.clear()

                    target_set.discard(author_id)
                    if not target_set:
                        break

            if not target_set:
                logger.info("All target researchers found!")
                break

            if (file_idx + 1) % 20 == 0:
                logger.info(f"Progress: {file_idx + 1}/{len(keys)} files, {total_found} found")

        except Exception as e:
            logger.warning(f"Error reading {key}: {e}")

    if batch:
        await update_topics_batch(batch)

    logger.info(f"S3 mode done: {total_found} found, {len(target_set)} still missing")


async def main():
    parser = argparse.ArgumentParser(description="Update researcher topics")
    parser.add_argument("--mode", choices=["api", "s3"], default="api")
    args = parser.parse_args()

    start = time.time()

    target_ids = await get_null_topic_ids()
    if not target_ids:
        logger.info("No researchers with null topics. Done.")
        return

    if args.mode == "api":
        await run_api_mode(target_ids)
    else:
        await run_s3_mode(target_ids)

    # 결과 확인
    async with AsyncSessionLocal() as db:
        from sqlalchemy import func
        result = await db.execute(
            select(func.count()).select_from(Researcher).where(Researcher.topics.isnot(None))
        )
        count_with_topics = result.scalar_one()

    elapsed = time.time() - start
    logger.info(f"Total time: {elapsed:.1f}s. Researchers with topics: {count_with_topics}")


if __name__ == "__main__":
    asyncio.run(main())
