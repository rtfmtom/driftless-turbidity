"""Per-stream basin rainfall endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Basin, BasinRainfall, Stream
from driftless.schemas.rainfall import RainfallHour, RainfallSeriesOut

router = APIRouter(prefix="/api/streams", tags=["rainfall"])


@router.get("/{stream_id}/rainfall", response_model=RainfallSeriesOut)
def get_stream_rainfall(
    stream_id: int,
    hours: int = Query(72, ge=1, le=24 * 90, description="Lookback window in hours"),
    db: Session = Depends(get_db),
) -> RainfallSeriesOut:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")

    basin = db.scalar(select(Basin).where(Basin.stream_id == stream_id))
    if basin is None:
        raise HTTPException(
            status_code=404,
            detail="no basin for this stream — run `python -m driftless.basins.delineate` first",
        )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.execute(
        select(BasinRainfall.ts, BasinRainfall.rainfall_mm)
        .where(BasinRainfall.basin_id == basin.id, BasinRainfall.ts >= cutoff)
        .order_by(BasinRainfall.ts)
    ).all()

    series = [
        RainfallHour(
            ts=r[0],
            rainfall_mm=float(r[1]) if r[1] is not None else None,
        )
        for r in rows
    ]
    total = sum((r.rainfall_mm or 0.0) for r in series)

    return RainfallSeriesOut(
        stream_id=stream_id,
        basin_id=basin.id,
        basin_area_km2=float(basin.area_km2) if basin.area_km2 is not None else None,
        hours_requested=hours,
        total_mm=round(total, 3),
        hours=series,
    )
