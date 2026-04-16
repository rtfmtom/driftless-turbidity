"""Request/response schemas for the /api/watch endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WatchCreateRequest(BaseModel):
    usgs_site_id: str = Field(..., min_length=3, max_length=20)
    stream_name: str | None = Field(default=None, max_length=200)
    relationship: str = Field(default="on_stream", pattern=r"^(on_stream|analog)$")


class WatchCreateResponse(BaseModel):
    stream_id: int
    stream_name: str
    usgs_site_id: str
    relationship: str
    created_stream: bool
    created_gauge: bool


class WatchedStream(BaseModel):
    stream_id: int
    stream_name: str
    usgs_site_id: str
    gauge_name: str
    relationship: str
