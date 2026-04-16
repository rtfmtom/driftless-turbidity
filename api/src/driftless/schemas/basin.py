"""Response schemas for the /api/streams/{id}/basin endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class BasinCharacteristicsOut(BaseModel):
    pct_row_crop: float | None = None
    pct_forest: float | None = None
    pct_pasture: float | None = None
    pct_developed: float | None = None
    pct_wetland: float | None = None
    baseflow_index: float | None = None
    mean_slope: float | None = None
    dominant_hsg: str | None = None
    runoff_curve_number: float | None = None
    computed_at: datetime | None = None


class BasinOut(BaseModel):
    stream_id: int
    area_km2: float | None = None
    source: str
    source_site_id: str | None = None
    computed_at: datetime
    # GeoJSON Geometry (typically a MultiPolygon). Kept as a plain dict so
    # we can hand it straight to MapLibre/Leaflet without rewrapping.
    polygon: dict[str, Any]
    characteristics: BasinCharacteristicsOut | None = None
