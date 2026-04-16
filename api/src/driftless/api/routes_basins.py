"""Basin endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Basin, BasinCharacteristics, Stream
from driftless.schemas.basin import BasinCharacteristicsOut, BasinOut

router = APIRouter(prefix="/api/streams", tags=["basins"])
basins_collection_router = APIRouter(prefix="/api/basins", tags=["basins"])


_BASINS_FC_SQL = text(
    """
    WITH latest_projection AS (
        SELECT DISTINCT ON (stream_id)
               stream_id, clarity_class, confidence, computed_at
        FROM projections
        ORDER BY stream_id, computed_at DESC
    )
    SELECT
        s.id            AS stream_id,
        s.name          AS stream_name,
        b.id            AS basin_id,
        b.area_km2      AS area_km2,
        bc.pct_row_crop AS pct_row_crop,
        lp.clarity_class,
        lp.confidence,
        lp.computed_at  AS clarity_computed_at,
        ST_AsGeoJSON(b.polygon) AS geojson
    FROM streams s
    JOIN basins b ON b.stream_id = s.id
    LEFT JOIN basin_characteristics bc ON bc.basin_id = b.id
    LEFT JOIN latest_projection lp ON lp.stream_id = s.id
    WHERE s.is_watched = true
    ORDER BY s.name
    """
)


@basins_collection_router.get("")
def list_basins(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return all watched-stream basins as a GeoJSON FeatureCollection.

    Each Feature's properties carry stream_id, stream_name, area_km2,
    pct_row_crop, clarity_class, confidence — everything the map needs
    to color and label the polygon.
    """
    rows = db.execute(_BASINS_FC_SQL).mappings().all()

    features: list[dict[str, Any]] = []
    for r in rows:
        features.append(
            {
                "type": "Feature",
                "id": r["basin_id"],
                "geometry": json.loads(r["geojson"]),
                "properties": {
                    "stream_id": r["stream_id"],
                    "stream_name": r["stream_name"],
                    "basin_id": r["basin_id"],
                    "area_km2": float(r["area_km2"]) if r["area_km2"] is not None else None,
                    "pct_row_crop": (
                        float(r["pct_row_crop"]) if r["pct_row_crop"] is not None else None
                    ),
                    "clarity_class": r["clarity_class"],
                    "confidence": r["confidence"],
                    "clarity_computed_at": (
                        r["clarity_computed_at"].isoformat()
                        if r["clarity_computed_at"] is not None
                        else None
                    ),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


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
