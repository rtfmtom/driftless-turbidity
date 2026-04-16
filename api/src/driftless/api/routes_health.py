"""Health check endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from driftless.db.session import engine
from driftless.scheduler import is_running as scheduler_running

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return liveness + dependency status."""
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("DB health check failed: %s", exc)
        db_status = "down"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "scheduler": "running" if scheduler_running() else "stopped",
    }
