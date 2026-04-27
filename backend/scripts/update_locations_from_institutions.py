"""
로컬 institutions 스냅샷에서 기관 좌표를 읽어 researchers.lat/lng 업데이트.

매칭 순서:
  1. institution_id (OpenAlex ID) 정확 매칭
  2. institution 이름 소문자 매칭 (fallback)

좌표에 ±100m 랜덤 지터 적용 (같은 기관 연구자들 겹침 방지).

Usage:
    cd backend
    .venv/bin/python -m scripts.update_locations_from_institutions
"""
import asyncio
import gzip
import json
import logging
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

INST_DIR = Path(__file__).resolve().parent.parent / "data" / "institutions"
JITTER_METERS = 10  # ±10m


def add_jitter(lat: float, lng: float) -> tuple[float, float]:
    """위도/경도에 ±JITTER_METERS 랜덤 오프셋 추가."""
    # 1도 위도 ≈ 111,320m
    lat_offset = (random.uniform(-1, 1) * JITTER_METERS) / 111_320
    # 1도 경도 ≈ 111,320 * cos(lat) m
    lng_offset = (random.uniform(-1, 1) * JITTER_METERS) / (111_320 * math.cos(math.radians(lat)))
    return lat + lat_offset, lng + lng_offset


def build_institution_maps() -> tuple[dict, dict]:
    """
    institutions 스냅샷 → 두 가지 매핑:
      id_map:   {openalex_id: {lat, lng, name, country}}   (예: "I12345")
      name_map: {display_name_lower: {...}}                 (fallback)
    """
    id_map = {}
    name_map = {}

    gz_files = sorted(INST_DIR.rglob("*.gz"))
    if not gz_files:
        logger.error(f"No .gz files in {INST_DIR}")
        return id_map, name_map

    logger.info(f"Reading {len(gz_files)} institution files...")
    total = with_coords = 0

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

                total += 1
                geo = inst.get("geo") or {}
                lat = geo.get("latitude")
                lng = geo.get("longitude")
                if lat is None or lng is None:
                    continue

                with_coords += 1
                raw_id = inst.get("id", "")
                inst_id = raw_id.split("/")[-1]  # "https://openalex.org/I12345" → "I12345"
                name = inst.get("display_name", "")
                country = inst.get("country_code", "")

                entry = {"lat": lat, "lng": lng, "name": name, "country": country}
                if inst_id:
                    id_map[inst_id] = entry
                if name:
                    name_map[name.lower()] = entry

    logger.info(f"Institutions: {total:,} total, {with_coords:,} with coords")
    logger.info(f"  ID map: {len(id_map):,} | Name map: {len(name_map):,}")
    return id_map, name_map


async def update_locations(id_map: dict, name_map: dict):
    """lat IS NULL인 연구자들 위치 업데이트 — ID 우선, 이름 fallback."""

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT id, institution_id, institution, country
            FROM researchers
            WHERE lat IS NULL
        """))
        rows = result.fetchall()

    logger.info(f"lat 없는 연구자: {len(rows):,}명")

    updated = not_found = id_matched = name_matched = 0
    batch = []

    for rid, inst_id, inst_name, country in rows:
        # 1순위: institution_id 매칭
        entry = id_map.get(inst_id) if inst_id else None
        if entry:
            id_matched += 1
        else:
            # 2순위: 이름 매칭
            entry = name_map.get(inst_name.lower()) if inst_name else None
            if entry:
                name_matched += 1

        if not entry:
            not_found += 1
            continue

        jlat, jlng = add_jitter(entry["lat"], entry["lng"])
        batch.append({
            "id":      rid,
            "lat":     jlat,
            "lng":     jlng,
            "institution": entry["name"],
            "country": entry["country"] or country,
        })

        if len(batch) >= 2000:
            await _flush(batch)
            updated += len(batch)
            logger.info(
                f"Updated: {updated:,} (ID매칭: {id_matched:,} | 이름매칭: {name_matched:,}) "
                f"| 미매칭: {not_found:,}"
            )
            batch.clear()

    if batch:
        await _flush(batch)
        updated += len(batch)

    logger.info(
        f"\n=== DONE ===\n"
        f"Updated  : {updated:,}\n"
        f"ID 매칭  : {id_matched:,}\n"
        f"이름 매칭: {name_matched:,}\n"
        f"미매칭   : {not_found:,}\n"
    )


async def _flush(batch: list[dict]):
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            UPDATE researchers SET
                lat         = :lat,
                lng         = :lng,
                institution = COALESCE(:institution, institution),
                country     = COALESCE(:country, country)
            WHERE id = :id
        """), batch)
        await db.commit()


async def main():
    if not INST_DIR.exists():
        logger.error(f"institutions 폴더 없음: {INST_DIR}")
        return

    id_map, name_map = build_institution_maps()
    if not id_map:
        logger.error("매핑 빌드 실패")
        return

    await update_locations(id_map, name_map)


if __name__ == "__main__":
    asyncio.run(main())
