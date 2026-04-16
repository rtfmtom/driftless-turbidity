"""Pydantic response schemas for the /api/streams endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
    gauges: list[GaugeOut]
