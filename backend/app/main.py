from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.database import engine, Base
from app.api.routes import researchers, benchmarks, map, search, compare, trending, leaderboard, progress
from app.models.collaboration import Collaboration
from app.models.paper import Paper, PaperAuthor, PaperAuthorAffiliation, PaperFacet, PaperQualityFlag  # noqa: F401 - ensure tables are registered
from app.services.scheduler import setup_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 테이블 생성
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 스케줄러 시작
    setup_scheduler()
    # 클러스터 캐시 백그라운드 워밍업
    import asyncio
    asyncio.create_task(_warmup_clusters())
    yield
    # 스케줄러 종료
    shutdown_scheduler()


async def _warmup_clusters():
    """서버 시작 후 클러스터 캐시를 백그라운드에서 미리 채운다."""
    import asyncio
    await asyncio.sleep(3)  # DB 연결 안정화 대기
    try:
        from app.db.database import AsyncSessionLocal
        from app.api.routes.researchers import _build_clusters_cache, _clusters_cache, _clusters_cache_lock
        async with _clusters_cache_lock:
            if _clusters_cache is None:
                async with AsyncSessionLocal() as db:
                    await _build_clusters_cache(db)
                    print("[startup] Clusters cache warmed up.")
    except Exception as e:
        print(f"[startup] Clusters warmup failed: {e}")


app = FastAPI(title="ResearcherWorld API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(researchers.router, prefix="/api")
app.include_router(benchmarks.router, prefix="/api")
app.include_router(map.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(compare.router, prefix="/api")
app.include_router(trending.router, prefix="/api")
app.include_router(leaderboard.router, prefix="/api")
app.include_router(progress.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
