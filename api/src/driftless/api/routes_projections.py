"""Projection endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Projection, Stream
from driftless.schemas.projection import (
    ProjectionOut,
    ProjectionPointOut,
    ProjectionSeriesOut,
)

router = APIRouter(prefix="/api/streams", tags=["projections"])


@router.get("/{stream_id}/projection", response_model=ProjectionOut)
def get_latest_projection(stream_id: int, db: Session = Depends(get_db)) -> ProjectionOut:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")

    proj = db.scalar(
        select(Projection)
        .where(Projection.stream_id == stream_id)
        .order_by(Projection.computed_at.desc())
        .limit(1)
    )
    if proj is None:
        raise HTTPException(
            status_code=404,
            detail="no projection yet — run `python -m driftless.projection.heuristic`",
        )

    return ProjectionOut(
        stream_id=proj.stream_id,
        computed_at=proj.computed_at,
        valid_from=proj.valid_from,
        valid_to=proj.valid_to,
        clarity_class=proj.clarity_class,
        confidence=proj.confidence,
        model_version=proj.model_version,
        feature_snapshot=proj.feature_snapshot,
    )


@router.get("/{stream_id}/projections", response_model=ProjectionSeriesOut)
def get_projection_history(
    stream_id: int,
    hours: int = Query(168, ge=1, le=24 * 90, description="Lookback window in hours"),
    db: Session = Depends(get_db),
) -> ProjectionSeriesOut:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.execute(
        select(Projection.computed_at, Projection.clarity_class, Projection.confidence)
        .where(Projection.stream_id == stream_id, Projection.computed_at >= cutoff)
        .order_by(Projection.computed_at)
    ).all()

    return ProjectionSeriesOut(
        stream_id=stream_id,
        hours_requested=hours,
        points=[
            ProjectionPointOut(
                computed_at=r[0],
                clarity_class=r[1],
                confidence=r[2],
            )
            for r in rows
        ],
    )
