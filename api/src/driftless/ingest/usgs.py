"""USGS NWIS ingest: instantaneous values and site metadata.

Run once from the CLI:

    python -m driftless.ingest.usgs --lookback-hours 2

Or register on APScheduler at a 15-minute cadence (see driftless.scheduler).
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from driftless.db.models import Gauge, GaugeReading
from driftless.db.session import SessionLocal
from driftless.ingest.sites import PARAMETER_CODES, seed_site_ids

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    site_info_updated: int = 0
    readings_upserted: int = 0
    sites_queried: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "site_info_updated": self.site_info_updated,
            "readings_upserted": self.readings_upserted,
            "sites_queried": self.sites_queried,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# USGS fetch helpers
# ---------------------------------------------------------------------------


def _unwrap(result):
    """`dataretrieval.nwis` functions return (df, meta) in modern versions but
    plain DataFrames in some older ones. Normalize to a DataFrame."""
    if isinstance(result, tuple) and result:
        return result[0]
    return result


def fetch_iv(
    site_ids: Iterable[str],
    parameter_codes: Iterable[str] = PARAMETER_CODES,
    lookback_hours: int = 2,
) -> pd.DataFrame:
    """Fetch instantaneous values for a batch of sites.

    Returns a wide DataFrame indexed by (site_no, datetime) with one column
    per parameter code plus companion ``<code>_cd`` qualifier columns.
    """
    from dataretrieval import nwis  # local import to keep module light

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)

    df = _unwrap(
        nwis.get_iv(
            sites=list(site_ids),
            parameterCd=list(parameter_codes),
            start=start.strftime("%Y-%m-%dT%H:%MZ"),
            end=end.strftime("%Y-%m-%dT%H:%MZ"),
        )
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    return df


def fetch_site_info(site_ids: Iterable[str]) -> pd.DataFrame:
    from dataretrieval import nwis

    df = _unwrap(nwis.get_info(sites=list(site_ids)))
    if df is None:
        return pd.DataFrame()
    return df.reset_index(drop=True) if df.index.name else df


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def iv_frame_to_rows(df: pd.DataFrame, parameter_codes: Iterable[str]) -> list[dict]:
    """Convert a wide IV DataFrame to long rows keyed on (site, ts, code)."""
    if df.empty:
        return []

    # Column containing the site id varies slightly across dataretrieval
    # versions: 'site_no' is standard. Fall back to first string column.
    site_col = "site_no" if "site_no" in df.columns else df.columns[0]
    ts_col = "datetime" if "datetime" in df.columns else df.columns[1]

    rows: list[dict] = []
    for code in parameter_codes:
        if code not in df.columns:
            continue
        qualifier_col = f"{code}_cd"
        sub = df[[site_col, ts_col, code] + ([qualifier_col] if qualifier_col in df.columns else [])]
        for _, r in sub.iterrows():
            val = r[code]
            if val is None or (isinstance(val, float) and math.isnan(val)):
                continue
            ts = r[ts_col]
            if not isinstance(ts, datetime):
                ts = pd.Timestamp(ts).to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            rows.append(
                {
                    "gauge_id": str(r[site_col]).zfill(8) if str(r[site_col]).isdigit() else str(r[site_col]),
                    "ts": ts,
                    "parameter_code": code,
                    "value": float(val),
                    "qualifier": str(r[qualifier_col]) if qualifier_col in sub.columns and not pd.isna(r[qualifier_col]) else None,
                }
            )
    return rows


def _parameters_from_info(info_row: pd.Series) -> dict[str, str | None]:
    """Best-effort extract of parameter metadata from an NWIS site-info row."""
    out: dict[str, str | None] = {}
    for code in PARAMETER_CODES:
        col = f"parm_cd_{code}"
        if col in info_row.index:
            out[code] = str(info_row[col])
    return out


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------


def upsert_gauges_from_info(session: Session, info_df: pd.DataFrame) -> int:
    if info_df is None or info_df.empty:
        return 0
    site_col = "site_no" if "site_no" in info_df.columns else info_df.columns[0]
    updated = 0
    for _, row in info_df.iterrows():
        site_id = str(row[site_col])
        lat = row.get("dec_lat_va") if "dec_lat_va" in row.index else None
        lon = row.get("dec_long_va") if "dec_long_va" in row.index else None
        name = row.get("station_nm") if "station_nm" in row.index else None

        values: dict[str, object] = {}
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not (math.isnan(lat) or math.isnan(lon)):
            values["location"] = f"SRID=4326;POINT({lon} {lat})"
        if isinstance(name, str) and name:
            values["name"] = name

        existing = session.get(Gauge, site_id)
        if existing is None:
            # Insert if missing. `name` falls back to site id.
            session.add(
                Gauge(
                    usgs_site_id=site_id,
                    name=values.get("name", site_id) if isinstance(values.get("name"), str) else site_id,
                )
            )
            session.flush()
            existing = session.get(Gauge, site_id)

        if existing is not None:
            if "location" in values:
                existing.location = values["location"]
            if "name" in values and values["name"]:
                existing.name = values["name"]  # type: ignore[assignment]
            updated += 1
    return updated


def upsert_readings(session: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    stmt = pg_insert(GaugeReading.__table__).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            GaugeReading.__table__.c.gauge_id,
            GaugeReading.__table__.c.ts,
            GaugeReading.__table__.c.parameter_code,
        ],
        set_={
            "value": stmt.excluded.value,
            "qualifier": stmt.excluded.qualifier,
        },
    )
    result = session.execute(stmt)
    return result.rowcount or len(rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def resolve_site_ids(session: Session, explicit: Iterable[str] | None = None) -> list[str]:
    """Pick the sites to ingest. Prefer the union of seeded + any locally
    watched gauges so that gauges added via /api/watch get polled too."""
    if explicit is not None:
        return list(explicit)

    site_ids: set[str] = set(seed_site_ids())
    for gauge_id in session.scalars(select(Gauge.usgs_site_id)):
        site_ids.add(gauge_id)
    return sorted(site_ids)


def ingest_once(
    session: Session,
    site_ids: Iterable[str] | None = None,
    lookback_hours: int = 2,
) -> IngestStats:
    stats = IngestStats()
    resolved = resolve_site_ids(session, site_ids)
    stats.sites_queried = resolved
    if not resolved:
        return stats

    logger.info("USGS ingest starting for %d sites (lookback=%dh)", len(resolved), lookback_hours)

    # 1) Site info (refresh location + parameters_available)
    try:
        info_df = fetch_site_info(resolved)
        stats.site_info_updated = upsert_gauges_from_info(session, info_df)
    except Exception as exc:  # noqa: BLE001 - log and keep going
        logger.warning("Site info fetch failed: %s", exc)
        stats.errors.append(f"site_info: {exc}")

    # 2) Instantaneous values
    try:
        iv_df = fetch_iv(resolved, lookback_hours=lookback_hours)
        rows = iv_frame_to_rows(iv_df, PARAMETER_CODES)
        # Only keep rows for gauges we actually have locally; this handles
        # the zero-padding quirk where NWIS strips leading zeros.
        existing_ids = set(session.scalars(select(Gauge.usgs_site_id)))
        filtered = []
        for r in rows:
            gid = r["gauge_id"]
            if gid in existing_ids:
                filtered.append(r)
                continue
            # Try the original un-padded id returned by NWIS.
            raw = gid.lstrip("0")
            matches = [eid for eid in existing_ids if eid.lstrip("0") == raw]
            if matches:
                r["gauge_id"] = matches[0]
                filtered.append(r)
        stats.readings_upserted = upsert_readings(session, filtered)
    except Exception as exc:  # noqa: BLE001
        logger.exception("IV fetch failed")
        stats.errors.append(f"iv: {exc}")

    session.commit()
    logger.info(
        "USGS ingest done: %d readings upserted across %d sites",
        stats.readings_upserted,
        len(resolved),
    )
    return stats


def ingest_once_job() -> None:
    """Wrapper suitable for APScheduler — handles its own session."""
    session = SessionLocal()
    try:
        ingest_once(session)
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled USGS ingest failed")
    finally:
        session.close()


def ingest_one_site_job(site_id: str) -> None:
    """One-shot ingest for a specific gauge (used after /api/watch adds it)."""
    session = SessionLocal()
    try:
        ingest_once(session, site_ids=[site_id])
    except Exception:  # noqa: BLE001
        logger.exception("Single-site USGS ingest failed for %s", site_id)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one USGS NWIS ingest pass")
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=2,
        help="Window of instantaneous values to pull (default: 2h)",
    )
    parser.add_argument(
        "--site",
        action="append",
        dest="sites",
        help="Limit to a specific USGS site id (repeat for multiple). "
        "Defaults to all seeded + locally known gauges.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    session = SessionLocal()
    try:
        stats = ingest_once(
            session,
            site_ids=args.sites,
            lookback_hours=args.lookback_hours,
        )
    finally:
        session.close()

    print(stats.as_dict())
    return 0 if not stats.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
