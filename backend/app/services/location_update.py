"""
기존 연구자 위치 정보 재보정 파이프라인.
- fast_fill_missing_locations: null country/institution → OpenAlex 배치 author 조회 (빠름)
- update_all_locations: works 기반 정밀 보정 (느림)
신규 수집 시에는 pipeline._upsert_batch에서 자동 처리됨.
"""

import asyncio
import httpx
from sqlalchemy import select, update

from app.db.database import AsyncSessionLocal
from app.models.researcher import Researcher
from app.services.openalex import fetch_works_institutions_batch, fetch_institution_coords
from app.core.config import settings

_status: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "updated": 0,
    "errors": 0,
    "last_error": None,
}

_fast_status: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "updated": 0,
    "errors": 0,
    "last_error": None,
}


def get_fast_status() -> dict:
    return dict(_fast_status)


async def fast_fill_missing_locations(limit: int = 50_000) -> None:
    """
    country + institution 둘 다 null인 연구자를 인용수 상위부터 OpenAlex 개별 조회.
    /authors/{id} 를 concurrency=30으로 병렬 처리 → last_known_institutions[0] 사용.
    50명 단위로 DB 커밋 + 기관 좌표 배치 조회.
    """
    import random

    global _fast_status
    _fast_status = {
        "running": True,
        "total": 0,
        "done": 0,
        "updated": 0,
        "errors": 0,
        "last_error": None,
    }

    BASE_URL = "https://api.openalex.org"
    CONCURRENCY = 30
    DB_BATCH = 50

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Researcher.id)
                    .where(Researcher.country.is_(None))
                    .where(Researcher.institution.is_(None))
                    .order_by(Researcher.citations.desc())
                    .limit(limit)
                )
            ).all()

        all_ids = [r.id for r in rows]
        _fast_status["total"] = len(all_ids)

        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def fetch_one(client: httpx.AsyncClient, aid: str) -> dict | None:
            """
            단일 연구자 OpenAlex 조회.
            1) last_known_institutions[0] 시도
            2) null이면 affiliations에서 가장 최근 연도 기관 사용
            """
            async with semaphore:
                try:
                    r = await client.get(
                        f"{BASE_URL}/authors/{aid}",
                        params={
                            "select": "id,last_known_institutions,affiliations",
                            "mailto": settings.OPENALEX_EMAIL,
                        },
                        timeout=15,
                    )
                    if r.status_code != 200:
                        return None
                    data = r.json()

                    # 1순위: last_known_institutions
                    inst = None
                    insts = data.get("last_known_institutions") or []
                    if insts:
                        inst = insts[0]

                    # 2순위: affiliations에서 가장 최근 연도 기관
                    if not inst:
                        affiliations = data.get("affiliations") or []
                        if affiliations:
                            # years 배열에서 최대값 기준 정렬
                            best = max(
                                affiliations,
                                key=lambda a: max(a.get("years") or [0]),
                            )
                            inst = best.get("institution") or {}

                    if not inst or not inst.get("country_code"):
                        return None

                    iid = (inst.get("id") or "").split("/")[-1]
                    return {
                        "aid": aid,
                        "inst_id": iid,
                        "inst_name": inst.get("display_name", "") or "",
                        "country": inst.get("country_code", "") or "",
                    }
                except Exception:
                    return None

        async with httpx.AsyncClient(timeout=20) as client:
            for i in range(0, len(all_ids), DB_BATCH):
                batch_ids = all_ids[i : i + DB_BATCH]

                # 병렬 조회
                results = await asyncio.gather(*[fetch_one(client, aid) for aid in batch_ids])
                found = [r for r in results if r and r["country"]]

                if found:
                    # 기관 좌표 배치 조회
                    inst_ids = list({r["inst_id"] for r in found if r["inst_id"]})
                    inst_coords = await fetch_institution_coords(inst_ids) if inst_ids else {}

                    # DB 업데이트
                    async with AsyncSessionLocal() as db:
                        for r in found:
                            coords = inst_coords.get(r["inst_id"])
                            values: dict = {
                                "institution": r["inst_name"] or None,
                                "country": r["country"],
                            }
                            if coords:
                                rng = random.Random(hash(r["aid"]) % 10000)
                                values["lat"] = coords[0] + rng.uniform(-0.003, 0.003)
                                values["lng"] = coords[1] + rng.uniform(-0.003, 0.003)
                            await db.execute(
                                update(Researcher)
                                .where(Researcher.id == r["aid"])
                                .values(**values)
                            )
                        await db.commit()
                    _fast_status["updated"] += len(found)
                else:
                    _fast_status["errors"] += len([r for r in results if r is None])

                _fast_status["done"] = min(i + DB_BATCH, len(all_ids))

    except Exception as exc:
        _fast_status["last_error"] = str(exc)[:200]
    finally:
        _fast_status["running"] = False


def get_status() -> dict:
    return dict(_status)


async def update_all_locations() -> None:
    """
    전체 연구자 위치 소급 보정.
    works 기반 소속(본인 논문 직접 명시) + OpenAlex 기관 좌표.
    """
    global _status
    _status = {
        "running": True,
        "total": 0,
        "done": 0,
        "updated": 0,
        "errors": 0,
        "last_error": None,
    }

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Researcher.id).order_by(Researcher.citations.desc())
                )
            ).all()

        all_ids = [r.id for r in rows]
        _status["total"] = len(all_ids)

        # 100명씩 배치 처리
        batch_size = 100
        for i in range(0, len(all_ids), batch_size):
            batch = all_ids[i : i + batch_size]
            try:
                # works 기반 소속 병렬 조회
                works_insts = await fetch_works_institutions_batch(batch, concurrency=10)

                # 기관 좌표 배치 조회
                inst_ids = [
                    v["inst_id"] for v in works_insts.values()
                    if v and v.get("inst_id")
                ]
                inst_coords = await fetch_institution_coords(list(set(inst_ids))) if inst_ids else {}

                # DB 업데이트
                for rid in batch:
                    try:
                        wi = works_insts.get(rid)
                        if not wi or not wi.get("inst_id"):
                            continue
                        coords = inst_coords.get(wi["inst_id"])
                        if not coords:
                            continue
                        async with AsyncSessionLocal() as db:
                            await db.execute(
                                update(Researcher)
                                .where(Researcher.id == rid)
                                .values(
                                    institution=wi["inst_name"] or None,
                                    country=wi["country"] or None,
                                    lat=coords[0],
                                    lng=coords[1],
                                )
                            )
                            await db.commit()
                        _status["updated"] += 1
                    except Exception as exc:
                        _status["errors"] += 1
                        _status["last_error"] = str(exc)[:200]

            except Exception as exc:
                _status["errors"] += 1
                _status["last_error"] = str(exc)[:200]

            _status["done"] = min(i + batch_size, len(all_ids))
            await asyncio.sleep(0.1)

    except Exception as exc:
        _status["last_error"] = str(exc)[:200]
    finally:
        _status["running"] = False
