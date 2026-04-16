"""APScheduler wiring for periodic USGS ingest."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from driftless.config import get_settings
from driftless.ingest.usgs import ingest_once_job, ingest_one_site_job

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

USGS_JOB_ID = "usgs_iv_ingest"


def _ensure_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    settings = get_settings()
    scheduler = _ensure_scheduler()
    if not settings.ingest_enabled:
        logger.info("Ingest disabled via INGEST_ENABLED=false; scheduler will not start the USGS job")
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
