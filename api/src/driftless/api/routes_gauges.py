"""Gauge discovery endpoints (USGS NWIS site-search)."""

from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import Gauge
from driftless.ingest.usgs import _unwrap  # reuse the helper
from driftless.schemas.gauge import GaugeSearchResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gauges", tags=["gauges"])

# Loose CONUS sanity bounds; refuses bogus or huge bboxes.
_MIN_LON, _MAX_LON = -130.0, -60.0
_MIN_LAT, _MAX_LAT = 20.0, 55.0


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in bbox.split(",")]
    if len(parts) != 4:
        raise HTTPException(
            status_code=400,
            detail="bbox must be 'west,south,east,north'",
        )
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bbox parse error: {exc}") from exc

    if not (west < east and south < north):
        raise HTTPException(
            status_code=400, detail="bbox must satisfy west<east and south<north"
        )
    if not (_MIN_LON <= west <= _MAX_LON and _MIN_LON <= east <= _MAX_LON):
        raise HTTPException(status_code=400, detail="bbox longitudes out of CONUS range")
    if not (_MIN_LAT <= south <= _MAX_LAT and _MIN_LAT <= north <= _MAX_LAT):
        raise HTTPException(status_code=400, detail="bbox latitudes out of CONUS range")
    # NWIS rejects very large bboxes; keep it below ~25 degrees per side.
    if (east - west) > 25 or (north - south) > 25:
        raise HTTPException(status_code=400, detail="bbox span too large (max 25°)")
    return west, south, east, north


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@router.get("/search", response_model=list[GaugeSearchResult])
def search_gauges(
    bbox: str = Query(..., description="west,south,east,north (decimal degrees)"),
    parameter_code: str = Query("00060", description="USGS parameter code"),
    db: Session = Depends(get_db),
) -> list[GaugeSearchResult]:
    west, south, east, north = _parse_bbox(bbox)

    from dataretrieval import nwis

    try:
        df = _unwrap(
            nwis.what_sites(
                bBox=f"{west},{south},{east},{north}",
                parameterCd=parameter_code,
                siteType="ST",
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("NWIS site search failed")
        raise HTTPException(status_code=502, detail=f"NWIS lookup failed: {exc}") from exc

    if df is None or df.empty:
        return []

    if df.index.name:
        df = df.reset_index()

    existing_ids = set(db.scalars(select(Gauge.usgs_site_id)))

    site_col = "site_no" if "site_no" in df.columns else df.columns[0]
    results: list[GaugeSearchResult] = []
    for _, row in df.iterrows():
        site_id = str(row[site_col])
        name = row.get("station_nm") if "station_nm" in row.index else site_id
        if not isinstance(name, str) or not name:
            name = site_id

        lat = _as_float(row.get("dec_lat_va"))
        lon = _as_float(row.get("dec_long_va"))

        param_codes: list[str] = []
        if "parm_cd" in row.index and isinstance(row["parm_cd"], str):
            param_codes = [p.strip() for p in row["parm_cd"].split(",") if p.strip()]
        elif parameter_code:
            param_codes = [parameter_code]

        results.append(
            GaugeSearchResult(
                usgs_site_id=site_id,
                name=name,
                latitude=lat,
                longitude=lon,
                parameter_codes=param_codes,
                already_watched=site_id in existing_ids,
            )
        )

    # Deduplicate on site id (NWIS sometimes returns multiple rows per site).
    seen: set[str] = set()
    deduped: list[GaugeSearchResult] = []
    for r in results:
        if r.usgs_site_id in seen:
            continue
        seen.add(r.usgs_site_id)
        deduped.append(r)

    deduped.sort(key=lambda r: r.name.lower())
    return deduped
