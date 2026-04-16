"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return a basic liveness signal.

    DB and scheduler status are added in later commits once those
    subsystems are wired up.
    """
    return {"status": "ok"}
