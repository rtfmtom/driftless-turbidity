"""Basin endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Basin, Stream
from driftless.schemas.basin import BasinOut

router = APIRouter(prefix="/api/streams", tags=["basins"])


@router.get("/{stream_id}/basin", response_model=BasinOut)
def get_basin(stream_id: int, db: Session = Depends(get_db)) -> BasinOut:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")

    # Pull the basin row with polygon emitted as GeoJSON directly from
    # PostGIS — cheaper than round-tripping through shapely.
    row = db.execute(
        select(
            Basin.stream_id,
            Basin.area_km2,
            Basin.source,
            Basin.source_site_id,
            Basin.computed_at,
            func.ST_AsGeoJSON(Basin.polygon).label("geojson"),
        ).where(Basin.stream_id == stream_id)
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="no basin for this stream — run `python -m driftless.basins.delineate`",
        )

    return BasinOut(
        stream_id=row.stream_id,
        area_km2=float(row.area_km2) if row.area_km2 is not None else None,
        source=row.source,
        source_site_id=row.source_site_id,
        computed_at=row.computed_at,
        polygon=json.loads(row.geojson),
    )
