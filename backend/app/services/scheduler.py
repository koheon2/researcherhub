"""
APScheduler 설정.
파이프라인을 6시간마다 자동 실행합니다.
"""
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler() -> None:
    from app.services.pipeline import run_pipeline  # 순환 import 방지

    scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(hours=6, start_date=datetime.now() + timedelta(hours=6)),
        id="pipeline_auto",
        kwargs={"max_batches": None, "per_page": 200, "resume": True},
        replace_existing=True,
        misfire_grace_time=1,     # 1초 이상 지연된 실행은 스킵 (재시작 시 자동 실행 방지)
    )
    scheduler.start()
    logger.info("Scheduler started — pipeline runs every 6 hours.")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
