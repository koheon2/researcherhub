"""
수집 자동화 파이프라인.
Phase 1: 유명 AI 기관 우선 수집
Phase 2: cursor 기반 전체 수집 (중단 후 재개 가능, 66만 명 전체 커버)
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from app.db.database import AsyncSessionLocal
from app.models.researcher import Researcher
from app.services.openalex import (
    FIELD_LABEL_MAP,
    fetch_ai_researchers,
    fetch_institution_coords,
    fetch_works_institutions_batch,
    parse_author,
)

logger = logging.getLogger(__name__)
STATE_FILE = Path(__file__).parent.parent.parent / "pipeline_state.json"

_status: dict = {
    "running": False,
    "last_run": None,
    "cursor": None,          # 마지막으로 완료한 OpenAlex cursor
    "total_in_db": 0,
    "phase": None,
    "batches_this_run": 0,
    "inserted_this_run": 0,
    "updated_this_run": 0,
    "skipped_this_run": 0,
    "errors_this_run": [],
}


def get_status() -> dict:
    return dict(_status)


def _load_state() -> None:
    if STATE_FILE.exists():
        try:
            saved = json.loads(STATE_FILE.read_text())
            for k in ("last_run", "cursor", "total_in_db"):
                if k in saved:
                    _status[k] = saved[k]
        except Exception as e:
            logger.warning(f"State load failed: {e}")


def _save_state() -> None:
    try:
        STATE_FILE.write_text(json.dumps({
            "last_run":    _status["last_run"],
            "cursor":      _status["cursor"],
            "total_in_db": _status["total_in_db"],
        }, indent=2))
    except Exception as e:
        logger.warning(f"State save failed: {e}")


async def _upsert_batch(
    db,
    raw_list: list[dict],
    inst_coords: dict,
    enrich_location: bool = False,
) -> tuple[int, int, int]:
    """
    raw_list 파싱 → works 기반 소속 보정 → upsert.
    (inserted, updated, skipped) 반환.
    """
    # 1. 파싱 (CS/AI 필터 포함)
    parsed: list[dict] = []
    for raw in raw_list:
        data = parse_author(raw, inst_coords=inst_coords)
        if data is None:
            continue
        parsed.append(data)

    skipped = len(raw_list) - len(parsed)
    if not parsed:
        return 0, 0, skipped

    # 2. works 기반 소속 보정 (enrich_location=True 일 때만)
    if enrich_location:
        author_ids = [d["id"] for d in parsed]
        try:
            works_insts = await fetch_works_institutions_batch(author_ids, concurrency=10)
        except Exception as e:
            logger.warning(f"works_institutions_batch failed, using fallback: {e}")
            works_insts = {}

        try:
            new_inst_ids = list({
                v["inst_id"]
                for v in works_insts.values()
                if v and v.get("inst_id") and v["inst_id"] not in inst_coords
            })
            if new_inst_ids:
                extra_coords = await fetch_institution_coords(new_inst_ids)
                inst_coords = {**inst_coords, **extra_coords}
        except Exception as e:
            logger.warning(f"extra coords fetch failed: {e}")

        for data in parsed:
            try:
                wi = works_insts.get(data["id"])
                if not wi or not wi.get("inst_id"):
                    continue
                coords = inst_coords.get(wi["inst_id"])
                if not coords:
                    continue
                data["institution"] = wi["inst_name"] or data["institution"]
                data["country"]     = wi["country"]   or data["country"]
                data["lat"]         = coords[0]
                data["lng"]         = coords[1]
            except Exception as e:
                logger.warning(f"override failed for {data.get('id')}: {e}")

    # 5. DB upsert
    inserted = updated = 0
    for data in parsed:
        existing = await db.get(Researcher, data["id"])
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(Researcher(**data))
            inserted += 1
    await db.commit()
    return inserted, updated, skipped


async def cleanup_non_cs(db) -> int:
    """CS/AI 분야가 아닌 기존 DB 레코드를 삭제합니다."""
    from sqlalchemy import delete
    from app.models.researcher import Researcher as R

    # 새 레이블(값) + 구 레이블(키) 모두 유효로 인정
    valid_labels = set(FIELD_LABEL_MAP.values()) | set(FIELD_LABEL_MAP.keys())
    result = await db.execute(
        delete(R).where(R.field.notin_(valid_labels))
    )
    await db.commit()
    removed = result.rowcount
    logger.info(f"Cleanup: removed {removed} non-CS/AI researchers")
    return removed


async def run_pipeline(
    max_batches: int | None = None,
    per_page: int = 200,
    resume: bool = True,
    enrich_location: bool = False,
) -> dict:
    """
    cursor 기반 전체 수집 (인용수 내림차순).
      - max_batches=None: 끝날 때까지 전부 수집
      - max_batches=N: N 배치만 수집 후 중단 (cursor 저장 → 재개 가능)
    """
    if _status["running"]:
        logger.warning("Pipeline already running — skipping.")
        return {"error": "already_running"}

    _load_state()
    _status["running"] = True
    _status["batches_this_run"] = 0
    _status["inserted_this_run"] = 0
    _status["updated_this_run"] = 0
    _status["skipped_this_run"] = 0
    _status["errors_this_run"] = []

    try:
        async with AsyncSessionLocal() as db:

            # ── cursor 기반 전체 수집 ──────────────────────────────────────────
            _status["phase"] = "phase2: cursor full scan"
            start_cursor = _status["cursor"] if resume and _status["cursor"] else "*"
            logger.info(f"Phase 2 start cursor: {start_cursor[:30] if start_cursor else '*'}...")

            cursor = start_cursor
            batch_num = 0

            while True:
                if max_batches is not None and batch_num >= max_batches:
                    logger.info(f"Reached max_batches={max_batches}, stopping.")
                    break

                try:
                    raw_list, next_cursor = await fetch_ai_researchers(
                        per_page=per_page, cursor=cursor
                    )
                except Exception as e:
                    err = f"Batch {batch_num} cursor={cursor[:20] if cursor else 'None'}: {e}"
                    logger.error(err)
                    _status["errors_this_run"].append(err)
                    # 429 Too Many Requests → 더 오래 대기
                    wait = 60.0 if "429" in str(e) else 5.0
                    await asyncio.sleep(wait)
                    continue

                if not raw_list:
                    logger.info("Empty response — end of results.")
                    break

                inst_ids = [
                    inst["id"]
                    for raw in raw_list
                    for inst in (raw.get("last_known_institutions") or [])[:1]
                    if inst.get("id")
                ]
                try:
                    inst_coords = await fetch_institution_coords(inst_ids)
                except Exception as e:
                    logger.warning(f"Coords failed batch {batch_num}: {e}")
                    inst_coords = {}

                ins, upd, skp = await _upsert_batch(
                    db, raw_list, inst_coords,
                    enrich_location=enrich_location,
                )
                _status["inserted_this_run"] += ins
                _status["updated_this_run"] += upd
                _status["skipped_this_run"] += skp
                _status["batches_this_run"] += 1
                batch_num += 1

                # cursor 저장 (중단돼도 재개 가능)
                if next_cursor:
                    _status["cursor"] = next_cursor
                    _save_state()
                else:
                    _status["cursor"] = None
                    _save_state()
                    logger.info("Cursor exhausted — full scan complete.")
                    break

                logger.info(
                    f"Batch {batch_num} ({len(raw_list)} authors): "
                    f"+{ins} ins / {upd} upd / {skp} skp "
                    f"| total ins={_status['inserted_this_run']}"
                )
                await asyncio.sleep(0.12)

            # ── 비CS 정리 ─────────────────────────────────────────────────────
            _status["phase"] = "cleanup"
            await cleanup_non_cs(db)

    except Exception as e:
        logger.error(f"Pipeline fatal: {e}")
        _status["errors_this_run"].append(str(e))
    finally:
        _status["running"] = False
        _status["phase"] = None
        _status["last_run"] = datetime.now().isoformat()
        _save_state()

    result = {
        "batches_fetched": _status["batches_this_run"],
        "inserted":        _status["inserted_this_run"],
        "updated":         _status["updated_this_run"],
        "skipped":         _status["skipped_this_run"],
        "errors":          len(_status["errors_this_run"]),
    }
    logger.info(f"Pipeline done: {result}")
    return result
