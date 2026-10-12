"""APScheduler：按各源 interval_hours 定时抓取。"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .db import SessionLocal
from .models import Source
from .fetcher import fetch_source

log = logging.getLogger("iptv.scheduler")
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_JOB_PREFIX = "fetch_source_"


def _job_id(source_id: int) -> str:
    return f"{_JOB_PREFIX}{source_id}"


def schedule_source(source: Source):
    """为单个源（重新）安排定时任务。"""
    remove_source(source.id)
    if not source.enabled:
        return
    hours = max(1, source.interval_hours or 12)
    scheduler.add_job(
        fetch_source,
        IntervalTrigger(hours=hours),
        id=_job_id(source.id),
        args=[source.id],
        replace_existing=True,
        misfire_grace_time=600,
        max_instances=1,  # 同一源不并发抓取
        coalesce=True,    # 错过的触发合并为一次
    )
    log.info("scheduled source %s every %sh", source.name, hours)


def remove_source(source_id: int):
    job = scheduler.get_job(_job_id(source_id))
    if job:
        job.remove()


def refresh_all_schedules():
    """启动时：为所有启用的源安排任务。"""
    db = SessionLocal()
    try:
        sources = db.query(Source).all()
    finally:
        db.close()
    for s in sources:
        try:
            schedule_source(s)
        except Exception as e:  # noqa: BLE001
            log.warning("schedule source %s failed: %s", s.id, e)


def start():
    if not scheduler.running:
        refresh_all_schedules()
        scheduler.start()
        log.info("scheduler started")


def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
