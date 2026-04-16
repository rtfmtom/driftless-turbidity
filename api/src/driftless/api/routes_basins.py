"""Basin endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Basin, BasinCharacteristics, Stream
from driftless.schemas.basin import BasinCharacteristicsOut, BasinOut

router = APIRouter(prefix="/api/streams", tags=["basins"])


def _load_characteristics(db: Session, basin_id: int) -> BasinCharacteristicsOut | None:
    row = db.scalar(
        select(BasinCharacteristics).where(BasinCharacteristics.basin_id == basin_id)
    )
    if row is None:
        return None
    return BasinCharacteristicsOut(
        pct_row_crop=float(row.pct_row_crop) if row.pct_row_crop is not None else None,
        pct_forest=float(row.pct_forest) if row.pct_forest is not None else None,
        pct_pasture=float(row.pct_pasture) if row.pct_pasture is not None else None,
        pct_developed=float(row.pct_developed) if row.pct_developed is not None else None,
        pct_wetland=float(row.pct_wetland) if row.pct_wetland is not None else None,
        baseflow_index=float(row.baseflow_index) if row.baseflow_index is not None else None,
        mean_slope=float(row.mean_slope) if row.mean_slope is not None else None,
        dominant_hsg=row.dominant_hsg,
        runoff_curve_number=(
            float(row.runoff_curve_number) if row.runoff_curve_number is not None else None
        ),
        computed_at=row.computed_at,
    )


@router.get("/{stream_id}/basin", response_model=BasinOut)
def get_basin(stream_id: int, db: Session = Depends(get_db)) -> BasinOut:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")

    # Pull the basin row with polygon emitted as GeoJSON directly from
    # PostGIS — cheaper than round-tripping through shapely.
    row = db.execute(
        select(
            Basin.id,
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
        characteristics=_load_characteristics(db, row.id),
    )
