import asyncio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.db.database import get_db
from app.models.researcher import Researcher
from app.models.collaboration import Collaboration
from app.services.graph import build_collaboration_graph, get_graph_status
from app.services import location_update
from app.schemas.researcher import ResearcherOut
from app.services.openalex import fetch_ai_researchers, fetch_institution_coords, parse_author
from app.services.pipeline import run_pipeline, get_status
from app.services.snapshot_pipeline import (
    run_snapshot_pipeline,
    get_snapshot_status,
    request_stop as snapshot_request_stop,
    reset_state as snapshot_reset_state,
)

router = APIRouter(prefix="/researchers", tags=["researchers"])

# 토픽 클러스터 인메모리 캐시 (서버 시작 시 1회 계산)
_clusters_cache: list | None = None
_clusters_cache_lock = asyncio.Lock()


# ── 조회 ──────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ResearcherOut])
async def list_researchers(
    field: str | None = Query(None),
    country: str | None = Query(None),
    limit: int = Query(500, le=10000),
    min_citations: int = Query(0),
    lat_min: float | None = Query(None),
    lat_max: float | None = Query(None),
    lng_min: float | None = Query(None),
    lng_max: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import and_
    q = select(Researcher).order_by(Researcher.citations.desc()).limit(limit)
    if field:
        q = q.where(Researcher.field == field)
    if country:
        q = q.where(Researcher.country == country)
    if min_citations > 0:
        q = q.where(Researcher.citations >= min_citations)
    if lat_min is not None and lat_max is not None:
        q = q.where(Researcher.lat >= lat_min).where(Researcher.lat <= lat_max)
    if lng_min is not None and lng_max is not None:
        # 날짜변경선(antimeridian) 처리: lng_min > lng_max 이면 범위가 180° 넘어감
        if lng_min <= lng_max:
            q = q.where(Researcher.lng >= lng_min).where(Researcher.lng <= lng_max)
        else:
            q = q.where(or_(Researcher.lng >= lng_min, Researcher.lng <= lng_max))
    result = await db.execute(q)
    return result.scalars().all()


_topic_names_cache: dict[str, str] | None = None

def _load_topic_names() -> dict[str, str]:
    global _topic_names_cache
    if _topic_names_cache is not None:
        return _topic_names_cache
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent.parent / "data" / "topic_names.json"
    if p.exists():
        _topic_names_cache = json.loads(p.read_text())
    else:
        _topic_names_cache = {}
    return _topic_names_cache


async def _build_clusters_cache(db: AsyncSession) -> list:
    from sqlalchemy import text as sa_text
    result = await db.execute(sa_text("""
        SELECT
            t.topic_id,
            COUNT(*)                    AS researcher_count,
            AVG(r.umap_x)               AS centroid_x,
            AVG(r.umap_y)               AS centroid_y,
            SUM(r.citations)            AS total_citations,
            mode() WITHIN GROUP (ORDER BY r.field) AS dominant_field
        FROM researchers r,
             jsonb_array_elements_text(r.topics::jsonb) AS t(topic_id)
        WHERE r.umap_x IS NOT NULL
          AND r.topics IS NOT NULL
          AND r.topics::text != 'null'
        GROUP BY t.topic_id
        HAVING COUNT(*) >= 3
        ORDER BY researcher_count DESC
        LIMIT 2000
    """))
    rows = result.fetchall()

    topic_names = _load_topic_names()

    top_topic_ids = [r[0] for r in rows[:50]]
    top_researchers_map: dict[str, list] = {}
    if top_topic_ids:
        placeholders = ",".join(f"'{tid}'" for tid in top_topic_ids)
        tr_result = await db.execute(sa_text(f"""
            SELECT DISTINCT ON (t.topic_id, r.citations)
                t.topic_id, r.id, r.name, r.citations
            FROM researchers r,
                 jsonb_array_elements_text(r.topics::jsonb) AS t(topic_id)
            WHERE t.topic_id IN ({placeholders})
              AND r.umap_x IS NOT NULL
            ORDER BY t.topic_id, r.citations DESC
        """))
        for topic_id, rid, name, citations in tr_result.fetchall():
            if topic_id not in top_researchers_map:
                top_researchers_map[topic_id] = []
            if len(top_researchers_map[topic_id]) < 3:
                top_researchers_map[topic_id].append({"id": rid, "name": name, "citations": citations or 0})

    return [
        {
            "topic_id": r[0],
            "topic_name": topic_names.get(r[0], r[0]),
            "researcher_count": r[1],
            "centroid_x": float(r[2]) if r[2] is not None else 0.0,
            "centroid_y": float(r[3]) if r[3] is not None else 0.0,
            "total_citations": int(r[4]) if r[4] is not None else 0,
            "dominant_field": r[5] or "AI",
            "top_researchers": top_researchers_map.get(r[0], []),
        }
        for r in rows
    ]


@router.get("/topics/clusters")
async def get_topic_clusters(
    min_researchers: int = Query(3, ge=1),
    limit: int = Query(500, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """캐시된 토픽 클러스터 반환. 첫 요청 시 계산, 이후 즉시 응답."""
    global _clusters_cache
    async with _clusters_cache_lock:
        if _clusters_cache is None:
            _clusters_cache = await _build_clusters_cache(db)

    filtered = [c for c in _clusters_cache if c["researcher_count"] >= min_researchers]
    return filtered[:limit]


@router.get("/by-openalex-ids", response_model=list[ResearcherOut])
async def get_researchers_by_ids(
    ids: str = Query(..., description="콤마로 구분된 OpenAlex author ID 목록 (예: A123,A456)"),
    db: AsyncSession = Depends(get_db),
):
    """OpenAlex author ID 목록으로 연구자 조회. Benchmark → Globe/Universe 연결에 사용."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:100]
    if not id_list:
        return []
    result = await db.execute(
        select(Researcher).where(Researcher.id.in_(id_list))
    )
    return result.scalars().all()


@router.get("/search", response_model=list[ResearcherOut])
async def search_researchers(
    q: str = Query(..., min_length=2),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Researcher)
        .where(func.lower(Researcher.name).contains(q.lower()))
        .limit(20)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/stats/count")
async def count_researchers(
    field: str | None = Query(None),
    country: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """연구자 수 반환 (field/country 필터 지원)."""
    q = select(func.count()).select_from(Researcher)
    if field:
        q = q.where(Researcher.field == field)
    if country:
        q = q.where(Researcher.country == country)
    count = await db.scalar(q)
    return {"count": count or 0}


@router.get("/stats/fields")
async def get_field_stats(db: AsyncSession = Depends(get_db)):
    """분야별 연구자 수 + 최고 인용수 반환. 좌측 ExplorerPanel에서 사용."""
    result = await db.execute(
        select(
            Researcher.field,
            func.count().label("count"),
            func.max(Researcher.citations).label("max_citations"),
        )
        .where(Researcher.lat.isnot(None))
        .group_by(Researcher.field)
        .order_by(func.count().desc())
    )
    return [
        {"field": r.field, "count": r.count, "max_citations": r.max_citations}
        for r in result
    ]


@router.get("/{researcher_id}/related", response_model=list[ResearcherOut])
async def get_related_researchers(
    researcher_id: str, db: AsyncSession = Depends(get_db)
):
    """
    복합 점수 기반 관련 연구자 반환.
    score = 공동저자(0~5) + 토픽 Jaccard(0~3) + 같은기관(0~1)
    """
    target = await db.get(Researcher, researcher_id)
    if not target:
        raise HTTPException(status_code=404, detail="Researcher not found")

    target_topics: set[str] = set(target.topics or [])
    target_inst: str | None = target.institution

    # ── 공동저자 조회 ──────────────────────────────────────────────────────
    collab_result = await db.execute(
        select(Collaboration).where(
            or_(
                Collaboration.researcher_a == researcher_id,
                Collaboration.researcher_b == researcher_id,
            )
        )
    )
    collabs = collab_result.scalars().all()
    coauthor_data: dict[str, int] = {}
    for c in collabs:
        other = c.researcher_b if c.researcher_a == researcher_id else c.researcher_a
        coauthor_data[other] = c.paper_count

    # ── 후보 연구자: 같은 분야 + 좌표 있음, 최대 200명 ─────────────────
    q = (
        select(Researcher)
        .where(
            Researcher.id != researcher_id,
            Researcher.field == target.field,
            Researcher.lat.isnot(None),
            Researcher.lng.isnot(None),
        )
        .order_by(Researcher.citations.desc())
        .limit(200)
    )
    # 공동저자는 다른 분야여도 포함
    if coauthor_data:
        coauthor_ids = list(coauthor_data.keys())
        q2 = (
            select(Researcher)
            .where(
                Researcher.id.in_(coauthor_ids),
                Researcher.lat.isnot(None),
                Researcher.lng.isnot(None),
            )
        )
        r2 = await db.execute(q2)
        extra = {r.id: r for r in r2.scalars().all()}
    else:
        extra = {}

    result = await db.execute(q)
    same_field = {r.id: r for r in result.scalars().all()}
    candidates = {**same_field, **extra}  # 합집합

    # ── 점수 계산 ──────────────────────────────────────────────────────────
    scored: list[tuple[float, Researcher]] = []
    for r in candidates.values():
        if r.id == researcher_id:
            continue

        # 토픽 Jaccard (0~1)
        r_topics: set[str] = set(r.topics or [])
        if target_topics and r_topics:
            inter = len(target_topics & r_topics)
            union = len(target_topics | r_topics)
            jaccard = inter / union if union > 0 else 0.0
        else:
            jaccard = 0.0

        # 공동저자 점수 (0~1, 3편 이상이면 최대)
        papers = coauthor_data.get(r.id, 0)
        coauthor_score = min(1.0, papers / 3.0)

        # 기관 일치 (0 or 1)
        inst_score = 1.0 if (target_inst and r.institution == target_inst) else 0.0

        # 종합 점수
        score = coauthor_score * 5.0 + jaccard * 3.0 + inst_score * 1.0

        if score > 0:
            scored.append((score, r))

    if scored:
        scored.sort(key=lambda x: (-x[0], -x[1].citations))
        return [r for _, r in scored[:8]]

    # fallback: 토픽/공동저자 데이터 없으면 인용수 순
    fallback = sorted(same_field.values(), key=lambda r: r.citations, reverse=True)
    return fallback[:8]


@router.get("/{researcher_id}", response_model=ResearcherOut)
async def get_researcher(researcher_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Researcher).where(Researcher.id == researcher_id))
    researcher = result.scalar_one_or_none()
    if not researcher:
        raise HTTPException(status_code=404, detail="Researcher not found")
    return researcher


# ── 파이프라인 ─────────────────────────────────────────────────────────────────

@router.get("/pipeline/status", tags=["pipeline"])
async def pipeline_status(db: AsyncSession = Depends(get_db)):
    """파이프라인 현재 상태와 DB 통계를 반환합니다."""
    count_result = await db.execute(select(func.count()).select_from(Researcher))
    total_in_db = count_result.scalar_one()

    field_result = await db.execute(
        select(Researcher.field, func.count().label("n"))
        .group_by(Researcher.field)
        .order_by(func.count().desc())
    )
    fields = [{"field": r.field, "count": r.n} for r in field_result]

    return {
        **get_status(),
        "db_total": total_in_db,
        "db_by_field": fields,
    }


@router.post("/pipeline/run", tags=["pipeline"])
async def pipeline_run(
    background_tasks: BackgroundTasks,
    max_batches: int | None = Query(None, description="최대 배치 수 (None=전체, 배치당 200명)"),
    per_page: int = Query(200, ge=1, le=200),
    resume: bool = Query(True, description="True: 이전 cursor부터 재개, False: 처음부터"),
    enrich_location: bool = Query(False, description="True: works 기반 소속 보정 포함 (느림)"),
):
    """
    파이프라인을 수동으로 즉시 실행합니다 (백그라운드).
    max_batches=None → 66만 명 전체 수집 (cursor 기반, 중단 후 재개 가능)
    max_batches=10  → 2000명만 수집
    """
    status = get_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Pipeline already running")

    background_tasks.add_task(run_pipeline, max_batches=max_batches, per_page=per_page, resume=resume, enrich_location=enrich_location)
    return {
        "message": "Pipeline started in background",
        "mode": "full scan" if max_batches is None else f"{max_batches} batches",
        "resume": resume,
        "enrich_location": enrich_location,
    }


@router.post("/pipeline/reset", tags=["pipeline"])
async def pipeline_reset():
    """커서를 초기화합니다 (다음 실행 시 1페이지부터 재수집)."""
    from app.services.pipeline import _status, STATE_FILE
    if _status["running"]:
        raise HTTPException(status_code=409, detail="Cannot reset while running")
    _status["last_page"] = 0
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return {"message": "Pipeline cursor reset"}


@router.post("/pipeline/cleanup", tags=["pipeline"])
async def pipeline_cleanup(db: AsyncSession = Depends(get_db)):
    """CS/AI 분야가 아닌 기존 레코드를 즉시 삭제합니다."""
    from app.services.pipeline import cleanup_non_cs
    removed = await cleanup_non_cs(db)
    return {"removed": removed}


# ── S3 스냅샷 파이프라인 ──────────────────────────────────────────────────────

@router.get("/snapshot/status", tags=["snapshot"])
async def snapshot_status():
    """S3 스냅샷 파이프라인 현재 상태를 반환합니다."""
    return get_snapshot_status()


@router.post("/snapshot/run", tags=["snapshot"])
async def snapshot_run(
    background_tasks: BackgroundTasks,
    resume: bool = Query(True, description="True: 이전 완료 파일 건너뛰고 재개"),
):
    """
    S3 스냅샷 기반 수집 파이프라인을 백그라운드로 시작합니다.
    OpenAlex API 크레딧 소모 없이 대량 수집이 가능합니다.
    """
    status = get_snapshot_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Snapshot pipeline already running")

    background_tasks.add_task(run_snapshot_pipeline, resume=resume)
    return {
        "message": "Snapshot pipeline started in background",
        "resume": resume,
    }


@router.post("/snapshot/stop", tags=["snapshot"])
async def snapshot_stop():
    """S3 스냅샷 파이프라인을 중지합니다. 현재 파일 처리 완료 후 중지됩니다."""
    status = get_snapshot_status()
    if not status["running"]:
        raise HTTPException(status_code=409, detail="Snapshot pipeline is not running")
    snapshot_request_stop()
    return {"message": "Stop requested. Pipeline will stop after current file."}


@router.post("/snapshot/reset", tags=["snapshot"])
async def snapshot_reset():
    """스냅샷 파이프라인 상태를 초기화합니다 (전체 재처리)."""
    status = get_snapshot_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Cannot reset while running")
    snapshot_reset_state()
    return {"message": "Snapshot state reset. Next run will process all files."}


# ── 그래프 ────────────────────────────────────────────────────────────────────

@router.get("/graph/status", tags=["graph"])
async def graph_status_endpoint():
    """공동저자 그래프 빌드 현황을 반환합니다."""
    status = get_graph_status()
    return status


@router.get("/graph/data", tags=["graph"])
async def graph_data(
    center_id: str = Query(..., description="중심 연구자 ID"),
    depth: int = Query(2, ge=1, le=3, description="연결 깊이"),
    max_nodes: int = Query(50, ge=1, le=200, description="최대 노드 수"),
    db: AsyncSession = Depends(get_db),
):
    """
    중심 연구자로부터 depth 단계까지의 협업 그래프를 반환합니다.
    협업 데이터가 없으면 같은 field의 유사 인용수 연구자들로 임시 edge를 생성합니다.
    """
    center = await db.get(Researcher, center_id)
    if not center:
        raise HTTPException(status_code=404, detail="Researcher not found")

    # BFS로 연결된 노드 탐색
    visited: set[str] = {center_id}
    frontier: set[str] = {center_id}
    edges_list: list[tuple[str, str, int]] = []

    for _ in range(depth):
        if len(visited) >= max_nodes:
            break
        next_frontier: set[str] = set()
        for node_id in frontier:
            collab_result = await db.execute(
                select(Collaboration).where(
                    or_(
                        Collaboration.researcher_a == node_id,
                        Collaboration.researcher_b == node_id,
                    )
                )
            )
            for c in collab_result.scalars().all():
                other = c.researcher_b if c.researcher_a == node_id else c.researcher_a
                a, b = sorted([node_id, other])
                if not any(ea == a and eb == b for ea, eb, _ in edges_list):
                    edges_list.append((a, b, c.paper_count))
                if other not in visited:
                    visited.add(other)
                    next_frontier.add(other)
                if len(visited) >= max_nodes:
                    break
            if len(visited) >= max_nodes:
                break
        frontier = next_frontier

    # 협업 데이터가 없으면 같은 field 기반 임시 edge 생성
    if not edges_list:
        edges_list, visited = await _generate_similarity_edges(
            db, center, max_nodes
        )

    # 노드 데이터 로드
    if visited:
        node_result = await db.execute(
            select(Researcher).where(Researcher.id.in_(list(visited)))
        )
        node_objs = node_result.scalars().all()
    else:
        node_objs = [center]

    nodes = [
        {
            "id": r.id,
            "name": r.name,
            "field": r.field,
            "citations": r.citations,
            "institution": r.institution,
            "country": r.country,
            "h_index": r.h_index,
            "works_count": r.works_count,
            "recent_papers": r.recent_papers,
            "lat": r.lat,
            "lng": r.lng,
            "umap_x": r.umap_x,
            "umap_y": r.umap_y,
            "openalex_url": r.openalex_url,
        }
        for r in node_objs
    ]

    edges = [
        {"source": a, "target": b, "weight": w}
        for a, b, w in edges_list
    ]

    return {"nodes": nodes, "edges": edges}


@router.get("/graph/top", tags=["graph"])
async def graph_top(
    field: str = Query("AI", description="분야 레이블"),
    limit: int = Query(100, ge=1, le=500, description="최대 연구자 수"),
    db: AsyncSession = Depends(get_db),
):
    """
    해당 field 상위 연구자들의 네트워크 그래프를 반환합니다.
    협업 데이터가 없으면 인용수 유사도 기반 임시 edge를 생성합니다.
    """
    # field 매칭: 정확히 일치하거나 포함 관계
    result = await db.execute(
        select(Researcher)
        .where(Researcher.field == field)
        .order_by(Researcher.citations.desc())
        .limit(limit)
    )
    researchers = list(result.scalars().all())
    if not researchers:
        return {"nodes": [], "edges": []}

    r_ids = {r.id for r in researchers}

    # 이 연구자들 사이의 기존 collaboration 조회
    edges_list: list[tuple[str, str, int]] = []
    if len(r_ids) > 1:
        collab_result = await db.execute(
            select(Collaboration).where(
                Collaboration.researcher_a.in_(r_ids),
                Collaboration.researcher_b.in_(r_ids),
            )
        )
        for c in collab_result.scalars().all():
            edges_list.append((c.researcher_a, c.researcher_b, c.paper_count))

    # 협업 데이터가 없으면 인용수 유사도 기반 edge 생성
    if not edges_list:
        edges_list = _generate_edges_for_group(researchers, max_per_node=10)

    nodes = [
        {
            "id": r.id,
            "name": r.name,
            "field": r.field,
            "citations": r.citations,
            "institution": r.institution,
            "country": r.country,
            "h_index": r.h_index,
            "works_count": r.works_count,
            "recent_papers": r.recent_papers,
            "lat": r.lat,
            "lng": r.lng,
            "umap_x": r.umap_x,
            "umap_y": r.umap_y,
            "openalex_url": r.openalex_url,
        }
        for r in researchers
    ]

    edges = [
        {"source": a, "target": b, "weight": w}
        for a, b, w in edges_list
    ]

    return {"nodes": nodes, "edges": edges}


async def _generate_similarity_edges(
    db: AsyncSession,
    center: Researcher,
    max_nodes: int,
) -> tuple[list[tuple[str, str, int]], set[str]]:
    """
    협업 데이터가 없을 때, 같은 field에서 인용수가 유사한 연구자를 연결합니다.
    """
    result = await db.execute(
        select(Researcher)
        .where(
            Researcher.field == center.field,
            Researcher.id != center.id,
        )
        .order_by(Researcher.citations.desc())
        .limit(max_nodes - 1)
    )
    neighbors = list(result.scalars().all())
    all_researchers = [center] + neighbors
    visited = {r.id for r in all_researchers}

    edges_list = _generate_edges_for_group(all_researchers, max_per_node=10)
    return edges_list, visited


def _generate_edges_for_group(
    researchers: list,
    max_per_node: int = 10,
) -> list[tuple[str, str, int]]:
    """
    연구자 그룹 내에서 인용수 유사도 기반 임시 edge를 생성합니다.
    같은 field, 인용수 차이 < 2배인 연구자들을 연결합니다.
    weight = min(cit_a, cit_b) / max(cit_a, cit_b) * 100
    """
    edges: list[tuple[str, str, int]] = []
    edge_count: dict[str, int] = {}

    # 인용수 내림차순 정렬
    sorted_r = sorted(researchers, key=lambda r: r.citations, reverse=True)

    for i, ra in enumerate(sorted_r):
        if edge_count.get(ra.id, 0) >= max_per_node:
            continue
        for j in range(i + 1, len(sorted_r)):
            rb = sorted_r[j]
            if edge_count.get(rb.id, 0) >= max_per_node:
                continue

            cit_a = max(ra.citations, 1)
            cit_b = max(rb.citations, 1)
            ratio = max(cit_a, cit_b) / min(cit_a, cit_b)
            if ratio >= 2.0:
                continue

            weight = int(min(cit_a, cit_b) / max(cit_a, cit_b) * 100)
            if weight < 1:
                continue

            a, b = sorted([ra.id, rb.id])
            edges.append((a, b, weight))
            edge_count[ra.id] = edge_count.get(ra.id, 0) + 1
            edge_count[rb.id] = edge_count.get(rb.id, 0) + 1

            if edge_count.get(ra.id, 0) >= max_per_node:
                break

    return edges


# ── 위치 업데이트 ─────────────────────────────────────────────────────────────

@router.get("/location/status", tags=["location"])
async def location_status():
    """위치 업데이트 진행 현황을 반환합니다."""
    return location_update.get_status()


@router.post("/location/update", tags=["location"])
async def start_location_update(background_tasks: BackgroundTasks):
    """
    전체 연구자의 소속·좌표를 works 기반으로 업데이트합니다 (정밀, 느림).
    """
    if location_update.get_status()["running"]:
        raise HTTPException(status_code=409, detail="Location update already running")
    background_tasks.add_task(location_update.update_all_locations)
    return {"message": "Location update started in background"}


@router.get("/location/fast-status", tags=["location"])
async def fast_location_status():
    """빠른 위치 보정 진행 현황을 반환합니다."""
    return location_update.get_fast_status()


@router.post("/location/fast-fill", tags=["location"])
async def start_fast_fill(
    background_tasks: BackgroundTasks,
    limit: int = Query(50000, description="처리할 최대 연구자 수 (인용수 상위부터)"),
):
    """
    country+institution이 null인 연구자를 OpenAlex 배치 조회로 빠르게 보정.
    50명씩 배치, last_known_institutions[0] 사용.
    """
    if location_update.get_fast_status()["running"]:
        raise HTTPException(status_code=409, detail="Fast fill already running")
    background_tasks.add_task(location_update.fast_fill_missing_locations, limit)
    return {"message": f"Fast fill started (limit={limit:,})"}



@router.post("/graph/build", tags=["graph"])
async def graph_build_endpoint(background_tasks: BackgroundTasks):
    """
    공동저자 그래프를 백그라운드에서 빌드합니다.
    - 각 연구자의 topics 업데이트
    - OpenAlex works API로 공동저자 관계 추출
    - Collaboration 테이블에 저장
    """
    status = get_graph_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Graph build already running")
    background_tasks.add_task(build_collaboration_graph)
    return {
        "message": "Graph build started in background",
        "note": "약 491명 x 3 페이지 = ~2분 소요 예상",
    }
