"""
OpenAlex S3 스냅샷 기반 수집 파이프라인.

퍼블릭 S3 버킷(s3://openalex)에서 Authors 데이터를 스트리밍으로 읽어
CS/AI 분야 연구자를 필터링하여 DB에 insert합니다.

API 크레딧 소모 없이 대량 수집이 가능합니다.
"""

import asyncio
import gzip
import json
import logging
import random
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from app.db.database import AsyncSessionLocal
from app.models.researcher import Researcher
from app.services.openalex import CS_AI_SUBFIELDS, FIELD_LABEL_MAP

logger = logging.getLogger(__name__)
STATE_FILE = Path(__file__).parent.parent.parent / "snapshot_state.json"

BUCKET = "openalex"
REGION = "us-east-1"
AUTHORS_PREFIX = "data/authors/"
INSTITUTIONS_PREFIX = "data/institutions/"
INST_CACHE_FILE = Path(__file__).parent.parent.parent / "institution_coords_cache.json"

# ── 전역 상태 ─────────────────────────────────────────────────────────────────

_status: dict[str, Any] = {
    "running": False,
    "stop_requested": False,
    "phase": None,               # "loading_institutions" | "processing_authors" | "done"
    "last_run": None,
    "total_files": 0,
    "files_processed": 0,
    "current_file": None,
    "inserted": 0,
    "updated": 0,
    "skipped": 0,
    "errors": [],
    "lines_in_current_file": 0,  # 현재 파일에서 처리한 라인 수
    "completed_files": [],       # 완료한 S3 키 목록 (재개용)
}


def get_snapshot_status() -> dict:
    out = {k: v for k, v in _status.items() if k != "completed_files"}
    out["completed_files_count"] = len(_status["completed_files"])
    return out


def _load_state() -> None:
    if STATE_FILE.exists():
        try:
            saved = json.loads(STATE_FILE.read_text())
            _status["completed_files"] = saved.get("completed_files", [])
            _status["last_run"] = saved.get("last_run")
        except Exception as e:
            logger.warning(f"Snapshot state load failed: {e}")


def _save_state() -> None:
    try:
        STATE_FILE.write_text(json.dumps({
            "completed_files": _status["completed_files"],
            "last_run": _status["last_run"],
        }, indent=2))
    except Exception as e:
        logger.warning(f"Snapshot state save failed: {e}")


def _get_s3_client():
    return boto3.client(
        "s3",
        region_name=REGION,
        config=Config(signature_version=UNSIGNED),
    )


# ── 기관 좌표 캐시 로드 ──────────────────────────────────────────────────────

def _load_institution_coords(s3_client) -> dict[str, tuple[float, float]]:
    """
    기관 좌표를 로드합니다. 로컬 캐시가 있으면 사용, 없으면 S3에서 다운로드 후 캐시 저장.
    Returns: {institution_id: (lat, lng)}
    """
    # 로컬 캐시 확인
    if INST_CACHE_FILE.exists():
        try:
            logger.info("Loading institution coords from local cache...")
            raw = json.loads(INST_CACHE_FILE.read_text())
            coords = {k: tuple(v) for k, v in raw.items()}
            logger.info(f"Loaded {len(coords)} institution coordinates from cache")
            return coords
        except Exception as e:
            logger.warning(f"Cache load failed, will re-download: {e}")

    # S3에서 다운로드
    coords: dict[str, tuple[float, float]] = {}

    paginator = s3_client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=INSTITUTIONS_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".gz"):
                keys.append(obj["Key"])

    logger.info(f"Loading institution coords from {len(keys)} S3 files...")

    for idx, key in enumerate(keys):
        try:
            resp = s3_client.get_object(Bucket=BUCKET, Key=key)
            with gzip.GzipFile(fileobj=resp["Body"]) as gz:
                for line_bytes in gz:
                    try:
                        record = json.loads(line_bytes)
                        inst_id = record.get("id", "").split("/")[-1]
                        geo = record.get("geo") or {}
                        lat = geo.get("latitude")
                        lng = geo.get("longitude")
                        if inst_id and lat is not None and lng is not None:
                            coords[inst_id] = (lat, lng)
                    except (json.JSONDecodeError, KeyError):
                        continue
            if (idx + 1) % 10 == 0:
                logger.info(f"  Institutions: {idx + 1}/{len(keys)} files, {len(coords)} coords so far")
        except Exception as e:
            logger.warning(f"Failed to load institutions from {key}: {e}")

    logger.info(f"Loaded {len(coords)} institution coordinates from S3")

    # 로컬 캐시 저장
    try:
        INST_CACHE_FILE.write_text(json.dumps(
            {k: list(v) for k, v in coords.items()}
        ))
        logger.info(f"Institution coords cached to {INST_CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save institution cache: {e}")

    return coords


# ── Author 파싱 (스냅샷 전용) ─────────────────────────────────────────────────

def _parse_snapshot_author(
    record: dict,
    inst_coords: dict[str, tuple[float, float]],
) -> dict | None:
    """
    스냅샷의 author 레코드를 DB 모델 형식으로 변환합니다.
    필터 조건:
      - cited_by_count > 50
      - topics 기반: field == "Computer Science" AND subfield in CS_AI_SUBFIELDS
      - topics가 비어있으면 x_concepts 폴백: "Computer science" 컨셉 보유 여부

    최신 파티션은 topics가 있고, 구 파티션은 topics가 비어 x_concepts만 있음.
    """
    # 인용수 필터
    if record.get("cited_by_count", 0) <= 50:
        return None

    # 분야 판별 전략:
    # 1) primary_topic 또는 topics[0]에서 field/subfield 확인 (최신 파티션)
    # 2) x_concepts에서 "Computer science" 존재 여부로 폴백 (구 파티션)
    primary = record.get("primary_topic")
    if not primary:
        topics = record.get("topics", [])
        primary = topics[0] if topics else None

    field_label = None

    if primary:
        # topics 기반 판별
        primary_field = (primary.get("field") or {}).get("display_name", "")
        primary_sf = (primary.get("subfield") or {}).get("display_name", "")

        if primary_field != "Computer Science":
            return None
        if primary_sf not in CS_AI_SUBFIELDS:
            return None

        field_label = FIELD_LABEL_MAP.get(primary_sf, primary_sf)
    else:
        # x_concepts 폴백: "Computer science" 컨셉이 최상위에 있어야 함
        x_concepts = record.get("x_concepts") or []
        if not x_concepts:
            return None

        # x_concepts는 score 내림차순 — 첫 번째가 가장 관련 높은 분야
        top_concept = x_concepts[0].get("display_name", "")
        if top_concept != "Computer science":
            return None

        # x_concepts에는 subfield 정보가 없으므로 일반 "Computer Science" 레이블 사용
        field_label = "Computer Science"

    # 기관 정보
    lki = record.get("last_known_institutions") or []
    inst = lki[0] if lki else {}
    inst_name = inst.get("display_name")
    country = inst.get("country_code")
    inst_id = inst.get("id", "").split("/")[-1] if inst.get("id") else None

    # 좌표 (기관 캐시에서 조회 + 랜덤 오프셋)
    author_id_str = record.get("id", "")
    author_id = author_id_str.split("/")[-1]
    lat = None
    lng = None
    if inst_id and inst_id in inst_coords:
        base_lat, base_lng = inst_coords[inst_id]
        rng = random.Random(hash(author_id) % 10000)
        lat = base_lat + rng.uniform(-0.003, 0.003)
        lng = base_lng + rng.uniform(-0.003, 0.003)

    # recent_papers: counts_by_year에서 최근 2년 works 합산
    current_year = datetime.now().year
    counts_by_year = record.get("counts_by_year") or []
    recent_papers = 0
    for entry in counts_by_year:
        if entry.get("year", 0) >= current_year - 1:
            recent_papers += entry.get("works_count", 0)

    summary = record.get("summary_stats") or {}

    # topics 추출 (상위 5개 topic ID)
    raw_topics = record.get("topics") or []
    topic_ids = [t.get("id", "").split("/")[-1] for t in raw_topics[:5] if t.get("id")]

    return {
        "id": author_id,
        "name": record.get("display_name", ""),
        "institution": inst_name,
        "country": country,
        "lat": lat,
        "lng": lng,
        "citations": record.get("cited_by_count", 0),
        "h_index": summary.get("h_index", 0),
        "works_count": record.get("works_count", 0),
        "recent_papers": recent_papers,
        "field": field_label,
        "topics": topic_ids if topic_ids else None,
        "umap_x": None,
        "umap_y": None,
        "openalex_url": author_id_str,
    }


# ── DB Upsert ─────────────────────────────────────────────────────────────────

async def _upsert_batch(db, parsed_list: list[dict]) -> tuple[int, int]:
    """
    파싱된 연구자 데이터를 DB에 upsert합니다.
    Returns: (inserted, updated)
    """
    inserted = updated = 0
    for data in parsed_list:
        existing = await db.get(Researcher, data["id"])
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(Researcher(**data))
            inserted += 1
    await db.commit()
    return inserted, updated


# ── 메인 파이프라인 ───────────────────────────────────────────────────────────

async def run_snapshot_pipeline(resume: bool = True) -> dict:
    """
    S3 스냅샷에서 CS/AI 연구자를 수집합니다.

    1단계: 기관 좌표 캐시 로드 (institutions 스냅샷)
    2단계: Authors 파일을 하나씩 스트리밍, 필터링, DB upsert

    resume=True: 이전에 완료한 파일은 건너뜁니다.
    """
    if _status["running"]:
        logger.warning("Snapshot pipeline already running")
        return {"error": "already_running"}

    _load_state()

    _status["running"] = True
    _status["stop_requested"] = False
    _status["inserted"] = 0
    _status["updated"] = 0
    _status["skipped"] = 0
    _status["errors"] = []
    _status["files_processed"] = 0

    completed_set = set(_status["completed_files"]) if resume else set()
    if not resume:
        _status["completed_files"] = []

    try:
        s3 = _get_s3_client()

        # ── 1단계: 기관 좌표 로드 ─────────────────────────────────────────
        _status["phase"] = "loading_institutions"
        logger.info("Phase 1: Loading institution coordinates from S3...")

        # 기관 로드는 동기(CPU-bound)이므로 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        inst_coords = await loop.run_in_executor(
            None, _load_institution_coords, s3
        )

        if _status["stop_requested"]:
            logger.info("Stop requested after institutions load")
            return _finalize()

        # ── 2단계: Authors 파일 목록 수집 ────────────────────────────────
        _status["phase"] = "processing_authors"
        logger.info("Phase 2: Listing author files...")

        paginator = s3.get_paginator("list_objects_v2")
        all_files: list[tuple[str, int]] = []  # (key, size)
        for page in paginator.paginate(Bucket=BUCKET, Prefix=AUTHORS_PREFIX):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".gz"):
                    all_files.append((obj["Key"], obj.get("Size", 0)))

        all_keys = [k for k, _ in all_files]

        # 큰 파일(=bulk 파티션) 우선 처리 → CS 연구자가 많은 파일 먼저
        pending_files = [(k, s) for k, s in all_files if k not in completed_set]
        pending_files.sort(key=lambda x: x[1], reverse=True)
        pending_keys = [k for k, _ in pending_files]
        _status["total_files"] = len(all_keys)
        _status["files_processed"] = len(all_keys) - len(pending_keys)

        logger.info(
            f"Total files: {len(all_keys)}, "
            f"Already done: {len(all_keys) - len(pending_keys)}, "
            f"Pending: {len(pending_keys)}"
        )

        # ── 3단계: 파일별 청크 스트리밍 처리 ────────────────────────────
        BATCH_SIZE = 200  # DB upsert 배치 크기

        for file_idx, key in enumerate(pending_keys):
            if _status["stop_requested"]:
                logger.info(f"Stop requested at file {file_idx}")
                break

            _status["current_file"] = key
            logger.info(f"Processing file {file_idx + 1}/{len(pending_keys)}: {key}")

            try:
                # Queue 기반: 파싱 스레드 -> asyncio 큐 -> DB upsert (실시간 진행)
                queue: asyncio.Queue[list[dict] | None] = asyncio.Queue(maxsize=4)
                file_matched = 0

                def _stream_and_enqueue():
                    """S3에서 스트리밍 읽기, BATCH_SIZE마다 큐에 넣기."""
                    nonlocal file_matched
                    batch: list[dict] = []
                    file_skipped = 0
                    line_count = 0
                    _status["lines_in_current_file"] = 0
                    resp = s3.get_object(Bucket=BUCKET, Key=key)
                    with gzip.GzipFile(fileobj=resp["Body"]) as gz:
                        for line_bytes in gz:
                            if _status["stop_requested"]:
                                break
                            line_count += 1
                            if line_count % 5000 == 0:
                                _status["lines_in_current_file"] = line_count
                            try:
                                record = json.loads(line_bytes)
                            except json.JSONDecodeError:
                                continue

                            parsed = _parse_snapshot_author(record, inst_coords)
                            if parsed:
                                batch.append(parsed)
                                if len(batch) >= BATCH_SIZE:
                                    file_matched += len(batch)
                                    # put은 blocking — maxsize=4면 메모리 제한됨
                                    asyncio.run_coroutine_threadsafe(
                                        queue.put(batch), loop
                                    ).result(timeout=300)
                                    batch = []
                            else:
                                file_skipped += 1

                    # 남은 배치
                    if batch:
                        file_matched += len(batch)
                        asyncio.run_coroutine_threadsafe(
                            queue.put(batch), loop
                        ).result(timeout=300)

                    _status["skipped"] += file_skipped
                    _status["lines_in_current_file"] = line_count
                    # sentinel: 파싱 완료 신호
                    asyncio.run_coroutine_threadsafe(
                        queue.put(None), loop
                    ).result(timeout=30)

                # 파싱 스레드 시작
                parse_future = loop.run_in_executor(None, _stream_and_enqueue)

                # DB upsert: 큐에서 배치를 꺼내 즉시 insert (실시간 진행)
                async with AsyncSessionLocal() as db:
                    while True:
                        batch = await queue.get()
                        if batch is None:
                            break  # 파싱 완료
                        if _status["stop_requested"]:
                            break
                        ins, upd = await _upsert_batch(db, batch)
                        _status["inserted"] += ins
                        _status["updated"] += upd

                # 파싱 스레드 완료 대기
                await parse_future

                # 파일 완료 기록
                _status["completed_files"].append(key)
                _status["files_processed"] += 1
                _save_state()

                logger.info(
                    f"File done: {key} | "
                    f"+{file_matched} matched | "
                    f"Total ins={_status['inserted']}, upd={_status['updated']}"
                )

            except Exception as e:
                err_msg = f"Error processing {key}: {e}"
                logger.error(err_msg)
                _status["errors"].append(err_msg)
                # 파일 하나 실패해도 계속 진행
                continue

            # S3 요청 간 약간의 딜레이
            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Snapshot pipeline fatal error: {e}")
        _status["errors"].append(f"Fatal: {e}")
    finally:
        return _finalize()


def _finalize() -> dict:
    _status["running"] = False
    _status["phase"] = "done"
    _status["current_file"] = None
    _status["last_run"] = datetime.now().isoformat()
    _save_state()

    result = {
        "files_processed": _status["files_processed"],
        "total_files": _status["total_files"],
        "inserted": _status["inserted"],
        "updated": _status["updated"],
        "skipped": _status["skipped"],
        "errors": len(_status["errors"]),
    }
    logger.info(f"Snapshot pipeline done: {result}")
    return result


def request_stop() -> None:
    """파이프라인 중지 요청. 현재 파일 처리 완료 후 중지됩니다."""
    _status["stop_requested"] = True


def reset_state() -> None:
    """완료 파일 목록을 초기화합니다 (다음 실행 시 전체 재처리)."""
    _status["completed_files"] = []
    if STATE_FILE.exists():
        STATE_FILE.unlink()
