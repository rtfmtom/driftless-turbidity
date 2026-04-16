"""Watch-list streams endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.db.models import GaugeReading, Stream, StreamGaugeLink
from driftless.schemas.stream import (
    GaugeOut,
    GaugeReadingPoint,
    GaugeReadingSeriesOut,
    ReadingOut,
    StreamOut,
)

router = APIRouter(prefix="/api", tags=["streams"])


# One row per (stream, gauge, parameter_code) with the latest reading for
# that combination. DISTINCT ON is the cleanest Postgres idiom here.
_STREAMS_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (gauge_id, parameter_code)
               gauge_id, parameter_code, ts, value, qualifier
        FROM gauge_readings
        ORDER BY gauge_id, parameter_code, ts DESC
    ),
    rain_24h AS (
        SELECT basin_id, SUM(rainfall_mm) AS mm
        FROM basin_rainfall
        WHERE ts >= NOW() - INTERVAL '24 hours'
        GROUP BY basin_id
    ),
    latest_projection AS (
        SELECT DISTINCT ON (stream_id)
               stream_id, computed_at, clarity_class, confidence
        FROM projections
        ORDER BY stream_id, computed_at DESC
    )
    SELECT
        s.id                    AS stream_id,
        s.name                  AS stream_name,
        s.wi_dnr_class          AS wi_dnr_class,
        s.is_watched            AS is_watched,
        b.area_km2              AS basin_area_km2,
        bc.pct_row_crop         AS pct_row_crop,
        bc.runoff_curve_number  AS runoff_curve_number,
        bc.dominant_hsg         AS dominant_hsg,
        r.mm                    AS rainfall_24h_mm,
        lp.clarity_class        AS clarity_class,
        lp.confidence           AS clarity_confidence,
        lp.computed_at          AS clarity_computed_at,
        g.usgs_site_id          AS site_id,
        g.name                  AS gauge_name,
        sgl.relationship        AS relationship,
        l.parameter_code,
        l.ts,
        l.value,
        l.qualifier
    FROM streams s
    JOIN stream_gauge_links sgl ON sgl.stream_id = s.id
    JOIN gauges g ON g.usgs_site_id = sgl.usgs_site_id
    LEFT JOIN basins b ON b.stream_id = s.id
    LEFT JOIN basin_characteristics bc ON bc.basin_id = b.id
    LEFT JOIN rain_24h r ON r.basin_id = b.id
    LEFT JOIN latest_projection lp ON lp.stream_id = s.id
    LEFT JOIN latest l ON l.gauge_id = g.usgs_site_id
    WHERE s.is_watched = true
    ORDER BY s.name, g.usgs_site_id, l.parameter_code
    """
)


@router.get("/streams", response_model=list[StreamOut])
def list_streams(db: Session = Depends(get_db)) -> list[StreamOut]:
    rows = db.execute(_STREAMS_SQL).mappings().all()

    streams_by_id: dict[int, StreamOut] = {}
    gauges_by_key: dict[tuple[int, str], GaugeOut] = {}

    for row in rows:
        stream_id = row["stream_id"]
        site_id = row["site_id"]

        if stream_id not in streams_by_id:
            streams_by_id[stream_id] = StreamOut(
                id=stream_id,
                name=row["stream_name"],
                wi_dnr_class=row["wi_dnr_class"],
                is_watched=row["is_watched"],
                basin_area_km2=(
                    float(row["basin_area_km2"])
                    if row["basin_area_km2"] is not None
                    else None
                ),
                pct_row_crop=(
                    float(row["pct_row_crop"])
                    if row["pct_row_crop"] is not None
                    else None
                ),
                runoff_curve_number=(
                    float(row["runoff_curve_number"])
                    if row["runoff_curve_number"] is not None
                    else None
                ),
                dominant_hsg=row["dominant_hsg"],
                rainfall_24h_mm=(
                    float(row["rainfall_24h_mm"])
                    if row["rainfall_24h_mm"] is not None
                    else None
                ),
                clarity_class=row["clarity_class"],
                clarity_confidence=row["clarity_confidence"],
                clarity_computed_at=row["clarity_computed_at"],
                gauges=[],
            )

        gkey = (stream_id, site_id)
        if gkey not in gauges_by_key:
            gauge = GaugeOut(
                usgs_site_id=site_id,
                name=row["gauge_name"],
                relationship=row["relationship"],
                latest_readings=[],
            )
            streams_by_id[stream_id].gauges.append(gauge)
            gauges_by_key[gkey] = gauge

        if row["parameter_code"] is not None:
            gauges_by_key[gkey].latest_readings.append(
                ReadingOut(
                    parameter_code=row["parameter_code"],
                    ts=row["ts"],
                    value=float(row["value"]) if row["value"] is not None else None,
                    qualifier=row["qualifier"],
                )
            )

    return list(streams_by_id.values())


# ---------------------------------------------------------------------------
# Single-stream + time-series endpoints (Chunk 3b)
# ---------------------------------------------------------------------------


@router.get("/streams/{stream_id}", response_model=StreamOut)
def get_stream(stream_id: int, db: Session = Depends(get_db)) -> StreamOut:
    """Detail view for a single stream — same shape as the watch list rows."""
    if db.get(Stream, stream_id) is None:
        raise HTTPException(status_code=404, detail="stream not found")

    # Filter the same enrichment query down to a single stream id. We
    # drop the is_watched filter so unwatched streams resolve too.
    rows = (
        db.execute(_SINGLE_STREAM_SQL, {"stream_id": stream_id}).mappings().all()
    )
    if not rows:
        # Shouldn't happen — Stream exists but has no gauge link.
        raise HTTPException(status_code=404, detail="stream has no gauge link")

    first = rows[0]
    out = StreamOut(
        id=first["stream_id"],
        name=first["stream_name"],
        wi_dnr_class=first["wi_dnr_class"],
        is_watched=first["is_watched"],
        basin_area_km2=_f(first["basin_area_km2"]),
        pct_row_crop=_f(first["pct_row_crop"]),
        runoff_curve_number=_f(first["runoff_curve_number"]),
        dominant_hsg=first["dominant_hsg"],
        rainfall_24h_mm=_f(first["rainfall_24h_mm"]),
        clarity_class=first["clarity_class"],
        clarity_confidence=first["clarity_confidence"],
        clarity_computed_at=first["clarity_computed_at"],
        gauges=[],
    )
    gauges_by_site: dict[str, GaugeOut] = {}
    for row in rows:
        site_id = row["site_id"]
        if site_id not in gauges_by_site:
            gauge = GaugeOut(
                usgs_site_id=site_id,
                name=row["gauge_name"],
                relationship=row["relationship"],
                latest_readings=[],
            )
            out.gauges.append(gauge)
            gauges_by_site[site_id] = gauge
        if row["parameter_code"] is not None:
            gauges_by_site[site_id].latest_readings.append(
                ReadingOut(
                    parameter_code=row["parameter_code"],
                    ts=row["ts"],
                    value=_f(row["value"]),
                    qualifier=row["qualifier"],
                )
            )
    return out


def _f(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# Same enrichment shape as _STREAMS_SQL but parametrized on stream_id and
# without the is_watched filter — used by the single-stream endpoint.
_SINGLE_STREAM_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (gauge_id, parameter_code)
               gauge_id, parameter_code, ts, value, qualifier
        FROM gauge_readings
        ORDER BY gauge_id, parameter_code, ts DESC
    ),
    rain_24h AS (
        SELECT basin_id, SUM(rainfall_mm) AS mm
        FROM basin_rainfall
        WHERE ts >= NOW() - INTERVAL '24 hours'
        GROUP BY basin_id
    ),
    latest_projection AS (
        SELECT DISTINCT ON (stream_id)
               stream_id, computed_at, clarity_class, confidence
        FROM projections
        ORDER BY stream_id, computed_at DESC
    )
    SELECT
        s.id                    AS stream_id,
        s.name                  AS stream_name,
        s.wi_dnr_class          AS wi_dnr_class,
        s.is_watched            AS is_watched,
        b.area_km2              AS basin_area_km2,
        bc.pct_row_crop         AS pct_row_crop,
        bc.runoff_curve_number  AS runoff_curve_number,
        bc.dominant_hsg         AS dominant_hsg,
        r.mm                    AS rainfall_24h_mm,
        lp.clarity_class        AS clarity_class,
        lp.confidence           AS clarity_confidence,
        lp.computed_at          AS clarity_computed_at,
        g.usgs_site_id          AS site_id,
        g.name                  AS gauge_name,
        sgl.relationship        AS relationship,
        l.parameter_code,
        l.ts,
        l.value,
        l.qualifier
    FROM streams s
    JOIN stream_gauge_links sgl ON sgl.stream_id = s.id
    JOIN gauges g ON g.usgs_site_id = sgl.usgs_site_id
    LEFT JOIN basins b ON b.stream_id = s.id
    LEFT JOIN basin_characteristics bc ON bc.basin_id = b.id
    LEFT JOIN rain_24h r ON r.basin_id = b.id
    LEFT JOIN latest_projection lp ON lp.stream_id = s.id
    LEFT JOIN latest l ON l.gauge_id = g.usgs_site_id
    WHERE s.id = :stream_id
    ORDER BY g.usgs_site_id, l.parameter_code
    """
)


@router.get("/streams/{stream_id}/gauge_readings", response_model=GaugeReadingSeriesOut)
def get_gauge_readings(
    stream_id: int,
    parameters: str = Query("00060,00065", description="Comma-separated parameter codes"),
    hours: int = Query(168, ge=1, le=24 * 90, description="Lookback window in hours"),
    db: Session = Depends(get_db),
) -> GaugeReadingSeriesOut:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")

    site_id = db.scalar(
        select(StreamGaugeLink.usgs_site_id)
        .where(
            StreamGaugeLink.stream_id == stream_id,
            StreamGaugeLink.relationship_kind == "on_stream",
        )
        .order_by(StreamGaugeLink.usgs_site_id)
        .limit(1)
    )
    if site_id is None:
        raise HTTPException(status_code=404, detail="stream has no on-stream gauge")

    codes = [c.strip() for c in parameters.split(",") if c.strip()]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = db.execute(
        select(
            GaugeReading.ts,
            GaugeReading.parameter_code,
            GaugeReading.value,
            GaugeReading.qualifier,
        )
        .where(
            GaugeReading.gauge_id == site_id,
            GaugeReading.parameter_code.in_(codes),
            GaugeReading.ts >= cutoff,
        )
        .order_by(GaugeReading.ts)
    ).all()

    return GaugeReadingSeriesOut(
        stream_id=stream_id,
        usgs_site_id=site_id,
        parameter_codes=codes,
        hours_requested=hours,
        points=[
            GaugeReadingPoint(
                ts=r[0],
                parameter_code=r[1],
                value=float(r[2]) if r[2] is not None else None,
                qualifier=r[3],
            )
            for r in rows
        ],
    )
