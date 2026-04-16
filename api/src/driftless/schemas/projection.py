"""Schemas for /api/streams/{id}/projection."""

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
