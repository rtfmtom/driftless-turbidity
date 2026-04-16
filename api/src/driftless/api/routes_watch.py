"""Watch-list management endpoints."""

from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Gauge, Stream, StreamGaugeLink
from driftless.ingest.usgs import _unwrap
from driftless.schemas.watch import (
    WatchCreateRequest,
    WatchCreateResponse,
    WatchedStream,
)
from driftless.scheduler import schedule_one_shot_site_ingest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watch", tags=["watch"])


def _fetch_and_upsert_gauge(db: Session, site_id: str) -> tuple[Gauge, bool]:
    """Return (gauge, created). Fetches NWIS site info if the gauge is new."""
    existing = db.get(Gauge, site_id)
    if existing is not None:
        return existing, False

    from dataretrieval import nwis

    try:
        df = _unwrap(nwis.get_info(sites=[site_id]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("NWIS get_info failed for %s", site_id)
        raise HTTPException(status_code=502, detail=f"NWIS lookup failed: {exc}") from exc

    station_name: str | None = None
    location_wkt: str | None = None
    params: dict[str, Any] = {}

    if df is not None and not df.empty:
        row = df.reset_index().iloc[0]
        if "station_nm" in row.index and isinstance(row["station_nm"], str):
            station_name = row["station_nm"]
        lat_raw = row.get("dec_lat_va") if "dec_lat_va" in row.index else None
        lon_raw = row.get("dec_long_va") if "dec_long_va" in row.index else None
        try:
            lat = float(lat_raw) if lat_raw is not None else None
            lon = float(lon_raw) if lon_raw is not None else None
        except (TypeError, ValueError):
            lat, lon = None, None
        if (
            isinstance(lat, float)
            and isinstance(lon, float)
            and not (math.isnan(lat) or math.isnan(lon))
        ):
            location_wkt = f"SRID=4326;POINT({lon} {lat})"

    gauge = Gauge(
        usgs_site_id=site_id,
        name=station_name or site_id,
        location=location_wkt,
        parameters_available=params,
    )
    db.add(gauge)
    db.flush()
    return gauge, True


@router.post("", response_model=WatchCreateResponse)
def add_to_watch(
    payload: WatchCreateRequest, db: Session = Depends(get_db)
) -> WatchCreateResponse:
    gauge, created_gauge = _fetch_and_upsert_gauge(db, payload.usgs_site_id)

    stream_name = payload.stream_name or gauge.name
    stream = db.scalar(select(Stream).where(Stream.name == stream_name))
    created_stream = False
    if stream is None:
        stream = Stream(name=stream_name, is_watched=True)
        db.add(stream)
        db.flush()
        created_stream = True
    elif not stream.is_watched:
        stream.is_watched = True

    link = db.get(StreamGaugeLink, (stream.id, gauge.usgs_site_id))
    if link is None:
        link = StreamGaugeLink(
            stream_id=stream.id,
            usgs_site_id=gauge.usgs_site_id,
            relationship_kind=payload.relationship,
        )
        db.add(link)
    else:
        link.relationship_kind = payload.relationship

    db.commit()

    # Kick off a one-shot ingest so the dashboard has data within seconds.
    try:
        schedule_one_shot_site_ingest(gauge.usgs_site_id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to schedule one-shot ingest for %s", gauge.usgs_site_id)

    return WatchCreateResponse(
        stream_id=stream.id,
        stream_name=stream.name,
        usgs_site_id=gauge.usgs_site_id,
        relationship=link.relationship_kind,
        created_stream=created_stream,
        created_gauge=created_gauge,
    )


@router.get("", response_model=list[WatchedStream])
def list_watched(db: Session = Depends(get_db)) -> list[WatchedStream]:
    rows = db.execute(
        select(
            Stream.id,
            Stream.name,
            Gauge.usgs_site_id,
            Gauge.name,
            StreamGaugeLink.relationship_kind,
        )
        .join(StreamGaugeLink, StreamGaugeLink.stream_id == Stream.id)
        .join(Gauge, Gauge.usgs_site_id == StreamGaugeLink.usgs_site_id)
        .where(Stream.is_watched.is_(True))
        .order_by(Stream.name, Gauge.usgs_site_id)
    ).all()

    return [
        WatchedStream(
            stream_id=r[0],
            stream_name=r[1],
            usgs_site_id=r[2],
            gauge_name=r[3],
            relationship=r[4],
        )
        for r in rows
    ]
