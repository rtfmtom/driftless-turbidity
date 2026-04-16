"""Layer A — feature computation per README §6.A.

For each stream, build a snapshot of the inputs the heuristic model
needs: basin-averaged rainfall windows from MRMS, the on-stream gauge's
current stage and 6-hour delta, and the static basin characteristics.

The result is a plain dataclass that ``projection.heuristic`` consumes
and ``projections.feature_snapshot`` persists verbatim so the UI can
explain *why* a clarity class was chosen.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class StreamFeatures:
    stream_id: int
    stream_name: str
    computed_at: datetime
    basin_id: int | None
    on_stream_site_id: str | None
    # Rainfall windows (mm)
    rainfall_1h_mm: float | None = None
    rainfall_6h_mm: float | None = None
    rainfall_24h_mm: float | None = None
    rainfall_72h_mm: float | None = None
    antecedent_wetness_7d_mm: float | None = None
    # Stage (ft, USGS native)
    stage_current_ft: float | None = None
    stage_6h_ago_ft: float | None = None
    stage_delta_6h_ft: float | None = None
    # Static basin characteristics
    drainage_area_km2: float | None = None
    pct_row_crop: float | None = None
    pct_forest: float | None = None
    pct_developed: float | None = None
    baseflow_index: float | None = None
    mean_slope_deg: float | None = None
    runoff_curve_number: float | None = None
    dominant_hsg: str | None = None

    def to_snapshot(self) -> dict[str, Any]:
        out = asdict(self)
        # JSONB-friendly: ISO-format the timestamp
        out["computed_at"] = self.computed_at.isoformat()
        return out


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

# Latest row metadata + rainfall sums + on-stream gauge id, all in one shot.
_FEATURES_SQL = text(
    """
    WITH base AS (
        SELECT
            s.id    AS stream_id,
            s.name  AS stream_name,
            b.id    AS basin_id,
            b.area_km2 AS drainage_area_km2,
            bc.pct_row_crop,
            bc.pct_forest,
            bc.pct_developed,
            bc.baseflow_index,
            bc.mean_slope          AS mean_slope_deg,
            bc.runoff_curve_number,
            bc.dominant_hsg,
            (
                SELECT sgl.usgs_site_id
                FROM stream_gauge_links sgl
                WHERE sgl.stream_id = s.id AND sgl.relationship = 'on_stream'
                ORDER BY sgl.usgs_site_id
                LIMIT 1
            ) AS on_stream_site_id
        FROM streams s
        LEFT JOIN basins b ON b.stream_id = s.id
        LEFT JOIN basin_characteristics bc ON bc.basin_id = b.id
        WHERE s.id = :stream_id
    ),
    rain AS (
        SELECT
            SUM(CASE WHEN ts >= :now - interval '1 hour'  THEN rainfall_mm ELSE 0 END) AS r1h,
            SUM(CASE WHEN ts >= :now - interval '6 hours' THEN rainfall_mm ELSE 0 END) AS r6h,
            SUM(CASE WHEN ts >= :now - interval '24 hours' THEN rainfall_mm ELSE 0 END) AS r24h,
            SUM(CASE WHEN ts >= :now - interval '72 hours' THEN rainfall_mm ELSE 0 END) AS r72h,
            SUM(CASE WHEN ts >= :now - interval '7 days'   THEN rainfall_mm ELSE 0 END) AS r7d
        FROM basin_rainfall br
        JOIN base ON br.basin_id = base.basin_id
        WHERE br.ts >= :now - interval '7 days' AND br.ts <= :now
    )
    SELECT
        base.*,
        rain.r1h, rain.r6h, rain.r24h, rain.r72h, rain.r7d
    FROM base, rain
    """
)

# Closest 00065 reading at-or-before a given timestamp.
_STAGE_AT_SQL = text(
    """
    SELECT value
    FROM gauge_readings
    WHERE gauge_id = :site_id
      AND parameter_code = '00065'
      AND ts <= :ts
    ORDER BY ts DESC
    LIMIT 1
    """
)


def _stage_at(session: Session, site_id: str, ts: datetime) -> float | None:
    val = session.execute(_STAGE_AT_SQL, {"site_id": site_id, "ts": ts}).scalar()
    return float(val) if val is not None else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_features(
    session: Session, stream_id: int, now: datetime | None = None
) -> StreamFeatures | None:
    """Build a feature snapshot for one watched stream.

    Returns None if the stream doesn't exist. Missing inputs (no basin,
    no rainfall data, no gauge) leave the corresponding fields at None
    and the heuristic will downgrade confidence accordingly.
    """
    now = now or datetime.now(timezone.utc)

    row = session.execute(_FEATURES_SQL, {"stream_id": stream_id, "now": now}).mappings().first()
    if row is None:
        return None

    feats = StreamFeatures(
        stream_id=row["stream_id"],
        stream_name=row["stream_name"],
        computed_at=now,
        basin_id=row["basin_id"],
        on_stream_site_id=row["on_stream_site_id"],
        rainfall_1h_mm=_to_float(row["r1h"]),
        rainfall_6h_mm=_to_float(row["r6h"]),
        rainfall_24h_mm=_to_float(row["r24h"]),
        rainfall_72h_mm=_to_float(row["r72h"]),
        antecedent_wetness_7d_mm=_to_float(row["r7d"]),
        drainage_area_km2=_to_float(row["drainage_area_km2"]),
        pct_row_crop=_to_float(row["pct_row_crop"]),
        pct_forest=_to_float(row["pct_forest"]),
        pct_developed=_to_float(row["pct_developed"]),
        baseflow_index=_to_float(row["baseflow_index"]),
        mean_slope_deg=_to_float(row["mean_slope_deg"]),
        runoff_curve_number=_to_float(row["runoff_curve_number"]),
        dominant_hsg=row["dominant_hsg"],
    )

    if feats.on_stream_site_id:
        feats.stage_current_ft = _stage_at(session, feats.on_stream_site_id, now)
        from datetime import timedelta

        feats.stage_6h_ago_ft = _stage_at(
            session, feats.on_stream_site_id, now - timedelta(hours=6)
        )
        if feats.stage_current_ft is not None and feats.stage_6h_ago_ft is not None:
            feats.stage_delta_6h_ft = round(
                feats.stage_current_ft - feats.stage_6h_ago_ft, 3
            )

    # Round rainfall to 3 decimals for cleaner JSON snapshots.
    for attr in (
        "rainfall_1h_mm",
        "rainfall_6h_mm",
        "rainfall_24h_mm",
        "rainfall_72h_mm",
        "antecedent_wetness_7d_mm",
    ):
        v = getattr(feats, attr)
        if v is not None:
            setattr(feats, attr, round(v, 3))

    return feats


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
