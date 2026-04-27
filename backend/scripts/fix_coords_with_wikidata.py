"""
Wikidata SPARQL로 주요 기관들의 정확한 캠퍼스 좌표를 조회하여 DB 업데이트.

흐름:
  1. DB에서 상위 N개 institution_id 조회 (연구자 수 기준)
  2. OpenAlex institution ID → Wikidata 엔티티 매핑 (P10283 외부 ID)
  3. Wikidata 좌표(P625) 조회 → 기관 좌표 업데이트
  4. ±100m jitter 적용

Usage:
    cd backend
    .venv/bin/python -m scripts.fix_coords_with_wikidata [--limit 500] [--dry-run]
"""
import argparse
import asyncio
import json
import logging
import math
import random
import sys
import time
from pathlib import Path

import urllib.request
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

JITTER_M = 10


def add_jitter(lat: float, lng: float) -> tuple[float, float]:
    dlat = (random.uniform(-1, 1) * JITTER_M) / 111_320
    dlng = (random.uniform(-1, 1) * JITTER_M) / (111_320 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


def query_wikidata(openalex_ids: list[str]) -> dict[str, tuple[float, float]]:
    """
    OpenAlex institution ID 목록 → {openalex_id: (lat, lng)}
    Wikidata P10283 = OpenAlex ID, P625 = coordinate location
    """
    # VALUES 절 구성: "Ixxxxx" 형식
    values_str = " ".join(f'"{oid}"' for oid in openalex_ids)

    sparql = f"""
SELECT ?openalexId ?lat ?lng WHERE {{
  VALUES ?openalexId {{ {values_str} }}
  ?item wdt:P10283 ?openalexId ;
        p:P625 ?coordStatement .
  ?coordStatement psv:P625 ?coord .
  ?coord wikibase:geoLatitude ?lat ;
         wikibase:geoLongitude ?lng .
}}
"""
    url = "https://query.wikidata.org/sparql"
    params = urllib.parse.urlencode({"query": sparql, "format": "json"})
    full_url = f"{url}?{params}"

    headers = {
        "User-Agent": "ResearcherHub/1.0 (institution coordinate fix; contact: admin@researcherhub.io)",
        "Accept": "application/json",
    }

    req = urllib.request.Request(full_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"Wikidata 쿼리 실패: {e}")
        return {}

    results = {}
    for binding in data.get("results", {}).get("bindings", []):
        oid = binding["openalexId"]["value"]
        lat = float(binding["lat"]["value"])
        lng = float(binding["lng"]["value"])
        results[oid] = (lat, lng)

    return results


async def get_top_institutions(limit: int) -> list[tuple[str, str, int]]:
    """상위 N개 institution (id, name, researcher_count)"""
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("""
            SELECT institution_id, institution, COUNT(*) as cnt
            FROM researchers
            WHERE institution_id IS NOT NULL AND lat IS NOT NULL
            GROUP BY institution_id, institution
            ORDER BY cnt DESC
            LIMIT :limit
        """), {"limit": limit})
        return r.fetchall()


async def update_institution_coords(
    institution_id: str,
    lat: float,
    lng: float,
    dry_run: bool,
) -> int:
    """해당 institution_id의 모든 연구자 lat/lng 업데이트"""
    if dry_run:
        return 0

    async with AsyncSessionLocal() as db:
        # 해당 기관 연구자 목록
        r = await db.execute(text("""
            SELECT id FROM researchers
            WHERE institution_id = :inst_id
        """), {"inst_id": institution_id})
        ids = [row[0] for row in r.fetchall()]

        if not ids:
            return 0

        batch = []
        for rid in ids:
            jlat, jlng = add_jitter(lat, lng)
            batch.append({"id": rid, "lat": jlat, "lng": jlng})

        # 배치 업데이트
        for i in range(0, len(batch), 2000):
            chunk = batch[i:i+2000]
            await db.execute(
                text("UPDATE researchers SET lat = :lat, lng = :lng WHERE id = :id"),
                chunk
            )
        await db.commit()
        return len(ids)


async def main(args):
    logger.info(f"상위 {args.limit}개 기관 조회 중...")
    institutions = await get_top_institutions(args.limit)
    logger.info(f"총 {len(institutions)}개 기관")

    openalex_ids = [row[0] for row in institutions]
    inst_map = {row[0]: (row[1], row[2]) for row in institutions}

    # Wikidata 배치 쿼리 (50개씩)
    batch_size = 50
    coords_map = {}
    for i in range(0, len(openalex_ids), batch_size):
        batch = openalex_ids[i:i+batch_size]
        logger.info(f"Wikidata 쿼리: {i+1}~{i+len(batch)} / {len(openalex_ids)}")
        result = query_wikidata(batch)
        coords_map.update(result)
        logger.info(f"  → {len(result)}개 좌표 찾음 (누적: {len(coords_map)})")
        time.sleep(1)  # Wikidata rate limit 준수

    logger.info(f"\n=== Wikidata 매핑 결과 ===")
    logger.info(f"조회: {len(openalex_ids)}, 찾음: {len(coords_map)}, 미찾음: {len(openalex_ids)-len(coords_map)}")

    if args.dry_run:
        logger.info("\n[DRY-RUN] 실제 업데이트 없음. 찾은 기관:")
        for oid, (lat, lng) in list(coords_map.items())[:20]:
            name, cnt = inst_map[oid]
            logger.info(f"  {cnt:>6}명  ({lat:.4f}, {lng:.4f})  {name}")
        return

    # 업데이트
    total_updated = 0
    for oid, (lat, lng) in coords_map.items():
        name, cnt = inst_map[oid]
        n = await update_institution_coords(oid, lat, lng, dry_run=False)
        total_updated += n
        logger.info(f"  Updated {n:>5}명  ({lat:.4f}, {lng:.4f})  {name}")

    logger.info(f"\n=== DONE ===\n기관: {len(coords_map)}개\n연구자: {total_updated:,}명 업데이트")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500, help="상위 N개 기관 (default: 500)")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 확인만")
    args = parser.parse_args()
    asyncio.run(main(args))
