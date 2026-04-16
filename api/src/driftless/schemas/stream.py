"""Pydantic response schemas for the /api/streams endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ClarityClass = Literal["clear", "tinged", "stained", "blown"]
ClarityConfidence = Literal["low", "medium", "high"]


class ReadingOut(BaseModel):
    parameter_code: str
    ts: datetime
    value: float | None
    qualifier: str | None = None


class GaugeOut(BaseModel):
    usgs_site_id: str
    name: str
    relationship: str
    latest_readings: list[ReadingOut]


class StreamOut(BaseModel):
    id: int
    name: str
    wi_dnr_class: str | None = None
    is_watched: bool
    basin_area_km2: float | None = None
    pct_row_crop: float | None = None
    runoff_curve_number: float | None = None
    dominant_hsg: str | None = None
    rainfall_24h_mm: float | None = None
    clarity_class: ClarityClass | None = None
    clarity_confidence: ClarityConfidence | None = None
    clarity_computed_at: datetime | None = None
    gauges: list[GaugeOut]


class GaugeReadingPoint(BaseModel):
    ts: datetime
    parameter_code: str
    value: float | None
    qualifier: str | None = None


class GaugeReadingSeriesOut(BaseModel):
    stream_id: int
    usgs_site_id: str
    parameter_codes: list[str]
    hours_requested: int
    points: list[GaugeReadingPoint]
