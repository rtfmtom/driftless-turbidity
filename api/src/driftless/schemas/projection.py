"""Schemas for /api/streams/{id}/projection(s)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProjectionOut(BaseModel):
    stream_id: int
    computed_at: datetime
    valid_from: datetime
    valid_to: datetime
    clarity_class: str
    confidence: str
    model_version: str
    feature_snapshot: dict[str, Any]


class ProjectionPointOut(BaseModel):
    """Compact projection record for time-series rendering."""

    computed_at: datetime
    clarity_class: str
    confidence: str


class ProjectionSeriesOut(BaseModel):
    stream_id: int
    hours_requested: int
    points: list[ProjectionPointOut]
