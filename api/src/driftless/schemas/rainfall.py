"""Response schemas for /api/streams/{id}/rainfall."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RainfallHour(BaseModel):
    ts: datetime
    rainfall_mm: float | None


class RainfallSeriesOut(BaseModel):
    stream_id: int
    basin_id: int
    basin_area_km2: float | None = None
    source: str = "mrms_qpe_01h_pass2"
    hours_requested: int
    total_mm: float
    hours: list[RainfallHour]
