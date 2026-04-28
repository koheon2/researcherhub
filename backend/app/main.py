from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.database import engine, Base
from app.api.routes import researchers, benchmarks, map, search, compare, trending, leaderboard, progress
from app.models.collaboration import Collaboration
from app.models.paper import InstitutionNameMatch, Paper, PaperAuthor, PaperAuthorAffiliation, PaperFacet, PaperQualityFlag, PublicationInstitutionFieldStat  # noqa: F401 - ensure tables are registered
from app.services.scheduler import setup_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 테이블 생성
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 스케줄러 시작
    setup_scheduler()
    yield
    # 스케줄러 종료
    shutdown_scheduler()


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
