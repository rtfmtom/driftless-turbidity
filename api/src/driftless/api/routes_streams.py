"""Watch-list streams endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from driftless.api.deps import get_db
from driftless.schemas.stream import GaugeOut, ReadingOut, StreamOut

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
    )
    SELECT
        s.id            AS stream_id,
        s.name          AS stream_name,
        s.wi_dnr_class  AS wi_dnr_class,
        s.is_watched    AS is_watched,
        g.usgs_site_id  AS site_id,
        g.name          AS gauge_name,
        sgl.relationship AS relationship,
        l.parameter_code,
        l.ts,
        l.value,
        l.qualifier
    FROM streams s
    JOIN stream_gauge_links sgl ON sgl.stream_id = s.id
    JOIN gauges g ON g.usgs_site_id = sgl.usgs_site_id
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
