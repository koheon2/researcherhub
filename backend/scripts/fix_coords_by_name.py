"""
OpenAlex ID 매핑이 안 된 기관들을 이름으로 Wikidata 검색하여 좌표 업데이트.

Usage:
    cd backend
    .venv/bin/python -m scripts.fix_coords_by_name [--dry-run]
"""
import argparse
import asyncio
import json
import logging
import math
import random
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

JITTER_M = 10

# 알려진 기관 좌표 (Wikidata/Wikipedia 확인값) — name-match fallback
KNOWN_COORDS = {
    "Seoul National University":                  (37.4603, 126.9521),
    "Samsung (South Korea)":                      (37.5145, 127.0631),  # Samsung Digital City, Suwon
    "Seoul National University of Science and Technology": (37.6490, 127.0776),
    "Sejong University":                          (37.5507, 127.0716),
    "Soongsil University":                        (37.4963, 126.9579),
    "Sogang University":                          (37.5512, 126.9408),
    "Dongguk University":                         (37.5587, 126.9982),
    "Kookmin University":                         (37.6019, 126.9200),
    "Ewha Womans University":                     (37.5619, 126.9463),
    "Konkuk University":                          (37.5408, 127.0793),
    "Kwangwoon University":                       (37.6184, 127.0561),
    "University of Seoul":                        (37.5833, 127.0578),
    "Korea Institute of Science and Technology":  (37.6039, 127.0570),
    "SK Group (South Korea)":                     (37.5706, 126.9819),
    "Korea Institute of Science and Technology Information": (37.3360, 127.4227),
    "Electronics and Telecommunications Research Institute": (36.3914, 127.3729),
    "LG (South Korea)":                           (37.5126, 126.8978),
    "Inha University":                            (37.4503, 126.6569),
    "Ajou University":                            (37.2792, 127.0436),
    "Chonnam National University":                (35.1768, 126.9093),
    # 기타 주요 기관 (도시 중심 집중이 심한 곳)
    "Centre National de la Recherche Scientifique": (48.8477, 2.2640),  # CNRS — Wikidata가 맞음
}


def query_wikidata_by_name(name: str) -> tuple[float, float] | None:
    """기관 이름으로 Wikidata 좌표 검색."""
    sparql = f"""
SELECT ?lat ?lng WHERE {{
  ?item rdfs:label "{name}"@en ;
        p:P625 ?coordStatement .
  ?coordStatement psv:P625 ?coord .
  ?coord wikibase:geoLatitude ?lat ;
         wikibase:geoLongitude ?lng .
}}
LIMIT 1
"""
    params = urllib.parse.urlencode({"query": sparql, "format": "json"})
    url = f"https://query.wikidata.org/sparql?{params}"
    headers = {
        "User-Agent": "ResearcherHub/1.0 (coord fix; educational)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        bindings = data.get("results", {}).get("bindings", [])
        if bindings:
            lat = float(bindings[0]["lat"]["value"])
            lng = float(bindings[0]["lng"]["value"])
            return lat, lng
    except Exception as e:
        logger.warning(f"Wikidata 쿼리 실패 ({name}): {e}")
    return None


def add_jitter(lat: float, lng: float) -> tuple[float, float]:
    dlat = (random.uniform(-1, 1) * JITTER_M) / 111_320
    dlng = (random.uniform(-1, 1) * JITTER_M) / (111_320 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


async def get_clustered_institutions(min_count: int = 50) -> list[tuple]:
    """연구자가 많은데 좌표가 '너무 깔끔한' (도시 중심) 기관 목록."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("""
            SELECT institution_id, institution, COUNT(*) as cnt,
                   round(avg(lat)::numeric, 4) as alat,
                   round(avg(lng)::numeric, 4) as alng,
                   round(stddev(lat)::numeric, 6) as slat
            FROM researchers
            WHERE lat IS NOT NULL AND institution_id IS NOT NULL
            GROUP BY institution_id, institution
            HAVING COUNT(*) >= :min AND round(stddev(lat)::numeric, 6) < 0.001
            ORDER BY cnt DESC
        """), {"min": min_count})
        return r.fetchall()


async def update_institution_coords(institution_id: str, lat: float, lng: float) -> int:
    async with AsyncSessionLocal() as db:
        r = await db.execute(text(
            "SELECT id FROM researchers WHERE institution_id = :inst_id"
        ), {"inst_id": institution_id})
        ids = [row[0] for row in r.fetchall()]

        batch = [{"id": rid, "lat": jlat, "lng": jlng}
                 for rid in ids
                 for jlat, jlng in [add_jitter(lat, lng)]]

        for i in range(0, len(batch), 2000):
            await db.execute(
                text("UPDATE researchers SET lat = :lat, lng = :lng WHERE id = :id"),
                batch[i:i+2000]
            )
        await db.commit()
        return len(ids)


async def main(args):
    logger.info("KNOWN_COORDS 기반 기관 좌표 수정 중...")

    # DB에서 institution_id 조회 (이름 → id 매핑)
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("""
            SELECT institution_id, institution, COUNT(*) as cnt,
                   round(avg(lat)::numeric, 4) as alat,
                   round(avg(lng)::numeric, 4) as alng
            FROM researchers
            WHERE institution_id IS NOT NULL AND lat IS NOT NULL
            GROUP BY institution_id, institution
        """))
        rows = r.fetchall()

    name_to_row = {row[1]: row for row in rows}

    total_updated = 0
    for name, (new_lat, new_lng) in KNOWN_COORDS.items():
        row = name_to_row.get(name)
        if not row:
            logger.warning(f"  DB에서 미발견: {name}")
            continue

        inst_id, _, cnt, alat, alng = row

        # 기존 좌표와 크게 다를 때만 업데이트 (0.01도 ≈ 1km)
        dist = math.sqrt((new_lat - float(alat))**2 + (new_lng - float(alng))**2)
        if dist < 0.01:
            logger.info(f"  변화 없음: {name} (거리 {dist*111:.0f}m)")
            continue

        logger.info(
            f"  {cnt:>5}명  {name}\n"
            f"         기존: ({alat}, {alng}) → 신규: ({new_lat:.4f}, {new_lng:.4f})  (거리: {dist*111:.1f}km)"
        )

        if not args.dry_run:
            n = await update_institution_coords(inst_id, new_lat, new_lng)
            total_updated += n
            logger.info(f"           → {n}명 업데이트")

    if not args.dry_run:
        logger.info(f"\n=== DONE === 연구자 {total_updated:,}명 업데이트")
    else:
        logger.info("\n[DRY-RUN] 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
