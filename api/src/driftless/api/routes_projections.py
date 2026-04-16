"""Projection endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Projection, Stream
from driftless.schemas.projection import ProjectionOut

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
