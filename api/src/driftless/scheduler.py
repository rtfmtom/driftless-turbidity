"""APScheduler wiring for periodic ingest jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from driftless.config import get_settings
from driftless.ingest.mrms import ingest_once_job as mrms_ingest_once_job
from driftless.ingest.usgs import ingest_once_job, ingest_one_site_job
from driftless.projection.heuristic import project_once_job

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

USGS_JOB_ID = "usgs_iv_ingest"
MRMS_JOB_ID = "mrms_hourly_ingest"
PROJECTION_JOB_ID = "projection_hourly"


def _ensure_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    settings = get_settings()
    scheduler = _ensure_scheduler()
    if not settings.ingest_enabled:
        logger.info("Ingest disabled via INGEST_ENABLED=false; scheduler will not start USGS/MRMS jobs")
    else:
        # Run ~5 s after boot so the DB/migrations have settled, then every N minutes.
        first_run = datetime.now(timezone.utc) + timedelta(seconds=5)
        scheduler.add_job(
            ingest_once_job,
            trigger=IntervalTrigger(minutes=settings.ingest_interval_minutes),
            id=USGS_JOB_ID,
            next_run_time=first_run,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        logger.info(
            "Scheduled USGS ingest every %d min, first run at %s",
            settings.ingest_interval_minutes,
            first_run.isoformat(),
        )

        if settings.mrms_enabled:
            # MRMS products land ~5-10 min after the top of each hour. Run
            # at HH:15 UTC to consume the previous hour's file.
            scheduler.add_job(
                mrms_ingest_once_job,
                trigger=CronTrigger(minute=15, timezone="UTC"),
                id=MRMS_JOB_ID,
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
            logger.info("Scheduled MRMS hourly ingest at HH:15 UTC")

        # Run heuristic projection a few minutes after MRMS lands so we
        # always project on the most recent hour's rainfall.
        scheduler.add_job(
            project_once_job,
            trigger=CronTrigger(minute=20, timezone="UTC"),
            id=PROJECTION_JOB_ID,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        logger.info("Scheduled hourly projection job at HH:20 UTC")

    if not scheduler.running:
        scheduler.start()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def schedule_one_shot_site_ingest(site_id: str) -> None:
    """Fire a one-off ingest for a single gauge (used by /api/watch)."""
    scheduler = _ensure_scheduler()
    if not scheduler.running:
        # If the scheduler isn't running (e.g. tests), fall back to a
        # synchronous call so the behavior is still predictable.
        ingest_one_site_job(site_id)
        return
    scheduler.add_job(
        ingest_one_site_job,
        trigger=DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=1)),
        args=[site_id],
        id=f"usgs_oneshot_{site_id}_{datetime.now(timezone.utc).timestamp():.0f}",
        coalesce=True,
        max_instances=1,
    )


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running
