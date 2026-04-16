"""Response schemas for the /api/gauges endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class GaugeSearchResult(BaseModel):
    usgs_site_id: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    parameter_codes: list[str] = []
    already_watched: bool = False
