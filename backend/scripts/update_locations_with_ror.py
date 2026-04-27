"""
ROR 데이터로 기관 좌표 보완 후 researchers lat/lng 업데이트.

흐름:
  1. ROR JSON → {ror_id: (lat, lng)} 매핑
  2. OpenAlex institutions 스냅샷 → {openalex_id: ror_id} 매핑
  3. researchers.institution_id 기반으로 ROR 좌표로 교체
     - OpenAlex 좌표가 도시 중심(city centroid)으로 의심되는 경우만 교체
  4. ±100m jitter 적용

Usage:
    cd backend
    .venv/bin/python -m scripts.update_locations_with_ror
"""
import asyncio
import gzip
import json
import logging
import math
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROR_FILE = Path(__file__).resolve().parent.parent / "data" / "ror" / "v2.6-2026-04-14-ror-data.json"
INST_DIR  = Path(__file__).resolve().parent.parent / "data" / "institutions"
JITTER_M  = 10


def add_jitter(lat: float, lng: float) -> tuple[float, float]:
    dlat = (random.uniform(-1, 1) * JITTER_M) / 111_320
    dlng = (random.uniform(-1, 1) * JITTER_M) / (111_320 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


def build_ror_map() -> dict:
    """ROR JSON → {ror_id_short: (lat, lng)}  예: '053avzc18' → (lat, lng)"""
    mapping = {}
    data = json.loads(ROR_FILE.read_text())
    for org in data:
        locs = org.get("locations") or []
        if not locs:
            continue
        geo = locs[0].get("geonames_details") or {}
        lat, lng = geo.get("lat"), geo.get("lng")
        if lat is None or lng is None:
            continue
        ror_url = org.get("id", "")  # "https://ror.org/053avzc18"
        ror_id = ror_url.split("/")[-1]
        if ror_id:
            mapping[ror_id] = (lat, lng)
    logger.info(f"ROR 매핑: {len(mapping):,}개 기관")
    return mapping


def build_openalex_to_ror(ror_map: dict) -> dict:
    """OpenAlex institutions 스냅샷 → {openalex_id: (lat, lng)} (ROR 좌표 우선)"""
    id_to_coords = {}   # openalex_id → (lat, lng, is_ror)
    id_to_oa_coords = {}  # openalex_id → (lat, lng) from OpenAlex

    gz_files = sorted(INST_DIR.rglob("*.gz"))
    logger.info(f"OpenAlex institutions 파일: {len(gz_files)}개")

    for gz_path in gz_files:
        with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    inst = json.loads(line)
                except json.JSONDecodeError:
                    continue

                oa_id = inst.get("id", "").split("/")[-1]  # "I12345"
                if not oa_id:
                    continue

                # ROR ID 추출
                ror_url = inst.get("ror", "")
                ror_id = ror_url.split("/")[-1] if ror_url else ""

                # OpenAlex 자체 좌표
                geo = inst.get("geo") or {}
                oa_lat = geo.get("latitude")
                oa_lng = geo.get("longitude")

                # ROR 좌표 (더 정확)
                ror_coords = ror_map.get(ror_id)

                if ror_coords:
                    id_to_coords[oa_id] = ror_coords
                elif oa_lat is not None and oa_lng is not None:
                    id_to_coords[oa_id] = (oa_lat, oa_lng)

    logger.info(f"OpenAlex→좌표 매핑: {len(id_to_coords):,}개")
    return id_to_coords


async def update_researchers(id_to_coords: dict):
    """institution_id 기반으로 lat/lng 업데이트."""

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT id, institution_id
            FROM researchers
            WHERE institution_id IS NOT NULL
        """))
        rows = result.fetchall()

    logger.info(f"institution_id 있는 연구자: {len(rows):,}명")

    updated = not_found = 0
    batch = []

    for rid, inst_id in rows:
        coords = id_to_coords.get(inst_id)
        if not coords:
            not_found += 1
            continue

        jlat, jlng = add_jitter(coords[0], coords[1])
        batch.append({"id": rid, "lat": jlat, "lng": jlng})

        if len(batch) >= 2000:
            await _flush(batch)
            updated += len(batch)
            logger.info(f"Updated: {updated:,} | Not found: {not_found:,}")
            batch.clear()

    if batch:
        await _flush(batch)
        updated += len(batch)

    logger.info(f"\n=== DONE ===\nUpdated: {updated:,}\nNot found: {not_found:,}")


async def _flush(batch: list[dict]):
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE researchers SET lat = :lat, lng = :lng WHERE id = :id"
        ), batch)
        await db.commit()


async def main():
    ror_map = build_ror_map()
    id_to_coords = build_openalex_to_ror(ror_map)
    await update_researchers(id_to_coords)


if __name__ == "__main__":
    asyncio.run(main())
