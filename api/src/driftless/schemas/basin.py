"""Response schemas for the /api/streams/{id}/basin endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class BasinOut(BaseModel):
    stream_id: int
    area_km2: float | None = None
    source: str
    source_site_id: str | None = None
    computed_at: datetime
    # GeoJSON Geometry (typically a MultiPolygon). Kept as a plain dict so
    # we can hand it straight to MapLibre/Leaflet without rewrapping.
    polygon: dict[str, Any]
