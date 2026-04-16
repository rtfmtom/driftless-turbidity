"""MRMS MultiSensor_QPE_01H_Pass2 rainfall ingest.

Downloads hourly gauge-corrected QPE GRIB2 files from the public
``s3://noaa-mrms-pds`` bucket, clips to a Driftless-area bounding box,
computes per-basin area-weighted mean rainfall, and upserts the
result into ``basin_rainfall``.

CLI::

    # Ingest the latest available hour
    python -m driftless.ingest.mrms

    # Backfill the last 90 days
    python -m driftless.ingest.mrms --backfill-hours 2160 --concurrency 4

    # Ingest a specific hour (UTC)
    python -m driftless.ingest.mrms --hour 2026-04-16T12:00

Raw GRIB2 files are NOT persisted. Only the per-basin hourly average
is kept in Postgres. This keeps storage to a few MB per year per
basin, and per README §10 "clip aggressively to a Driftless bounding
box on ingest rather than storing full CONUS".
"""

from __future__ import annotations

import argparse
import gzip
import io
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

import boto3
import numpy as np
from botocore import UNSIGNED
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from driftless.config import get_settings
from driftless.db.models import Basin, BasinRainfall
from driftless.db.session import SessionLocal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stats / helpers
# ---------------------------------------------------------------------------


@dataclass
class HourStats:
    ts: datetime
    s3_key: str | None = None
    basins_updated: int = 0
    rainfall_mm_mean: float | None = None
    status: str = "pending"  # pending | ok | missing | failed
    message: str = ""


@dataclass
class IngestStats:
    hours: list[HourStats] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out = {"ok": 0, "missing": 0, "failed": 0}
        for h in self.hours:
            out[h.status] = out.get(h.status, 0) + 1
        return out


def _s3_client():
    return boto3.client(
        "s3",
        config=Config(signature_version=UNSIGNED, retries={"max_attempts": 3, "mode": "standard"}),
    )


# ---------------------------------------------------------------------------
# S3 discovery
# ---------------------------------------------------------------------------


def find_key_for_hour(ts: datetime, s3=None) -> str | None:
    """Return the S3 key of the MRMS file covering ``ts`` (UTC top-of-hour).

    MRMS publishes these products every 2 minutes. For hourly ingestion
    we pick the file whose timestamp is within ``[ts, ts+1h)`` and
    closest to the start of the hour. If nothing is available, returns
    ``None``.
    """
    settings = get_settings()
    if s3 is None:
        s3 = _s3_client()

    date_prefix = f"{settings.mrms_product_prefix}/{ts:%Y%m%d}/"

    # Hourly files: filter keys containing '<YYYYMMDD>-HHMM' for the target hour.
    hour_token = f"{ts:%Y%m%d}-{ts:%H}"

    try:
        resp = s3.list_objects_v2(Bucket=settings.mrms_s3_bucket, Prefix=date_prefix)
    except ClientError as exc:
        logger.warning("S3 list failed for %s: %s", date_prefix, exc)
        return None

    contents = resp.get("Contents") or []
    candidates = [obj["Key"] for obj in contents if hour_token in obj["Key"]]
    if not candidates:
        return None

    # Pick the earliest file within the hour (closest to top-of-hour).
    candidates.sort()
    return candidates[0]


# ---------------------------------------------------------------------------
# Download + open
# ---------------------------------------------------------------------------


@contextmanager
def _download_grib(key: str, s3=None) -> Iterator[Path]:
    settings = get_settings()
    if s3 is None:
        s3 = _s3_client()

    # MRMS grib files are gzipped; decompress in memory then write to a
    # named temp file because cfgrib reads from a filesystem path.
    buf = io.BytesIO()
    s3.download_fileobj(settings.mrms_s3_bucket, key, buf)
    buf.seek(0)
    data = gzip.decompress(buf.read()) if key.endswith(".gz") else buf.read()

    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        yield Path(tmp.name)


def _open_clipped(grib_path: Path):
    """Open a GRIB2 file, clip to the configured Driftless bbox, return a
    rioxarray DataArray in EPSG:4326."""
    import rioxarray  # noqa: F401  # side-effect registers rio accessor
    import xarray as xr

    settings = get_settings()

    ds = xr.open_dataset(
        grib_path,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""},  # don't pollute tmpdir with .idx
        decode_timedelta=True,
    )
    # MRMS QPE products carry the data under 'unknown' or 'paramId_0' when
    # cfgrib can't pick a short name. Grab the first data variable.
    var_name = next(iter(ds.data_vars))
    da = ds[var_name]

    # Normalize longitude from 0..360 to -180..180 if needed.
    if "longitude" in da.coords:
        lon = da["longitude"]
        if float(lon.max()) > 180:
            da = da.assign_coords(longitude=(((lon + 180) % 360) - 180)).sortby("longitude")

    da = da.rio.write_crs("EPSG:4326", inplace=False)
    # rioxarray expects x/y dims; rename if needed.
    rename: dict[str, str] = {}
    if "longitude" in da.dims:
        rename["longitude"] = "x"
    if "latitude" in da.dims:
        rename["latitude"] = "y"
    if rename:
        da = da.rename(rename)

    # Clip to Driftless bbox. Use clip_box — fast, rectangular.
    da = da.rio.clip_box(
        minx=settings.mrms_clip_west,
        miny=settings.mrms_clip_south,
        maxx=settings.mrms_clip_east,
        maxy=settings.mrms_clip_north,
    )

    # MRMS uses -3 for missing, -1 for no-coverage. Mask to NaN.
    da = da.where(da >= 0)
    return da


# ---------------------------------------------------------------------------
# Per-basin aggregation
# ---------------------------------------------------------------------------


def _basin_rows(session: Session) -> list[tuple[int, str]]:
    """Return [(basin_id, geojson)] for all basins (GeoJSON from PostGIS)."""
    rows = session.execute(
        select(Basin.id, func.ST_AsGeoJSON(Basin.polygon))
    ).all()
    return [(r[0], r[1]) for r in rows]


def compute_basin_means(
    da, basin_rows: list[tuple[int, str]]
) -> dict[int, float | None]:
    """Clip a rainfall raster to each basin polygon and return the area-weighted
    mean rainfall (mm) per basin_id. Returns None for basins that don't
    intersect the raster at all."""
    import json

    out: dict[int, float | None] = {}
    for basin_id, geojson_str in basin_rows:
        geom = json.loads(geojson_str)
        try:
            clipped = da.rio.clip([geom], crs="EPSG:4326", drop=True, all_touched=True)
        except Exception as exc:  # noqa: BLE001
            # NoDataInBounds is the common case: basin outside the clipped frame.
            logger.debug("clip failed for basin %s: %s", basin_id, exc)
            out[basin_id] = None
            continue

        arr = clipped.values
        if arr.size == 0:
            out[basin_id] = None
            continue
        mean = np.nanmean(arr)
        if np.isnan(mean):
            out[basin_id] = None
        else:
            out[basin_id] = float(mean)
    return out


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def _upsert_rows(session: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    stmt = pg_insert(BasinRainfall.__table__).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[BasinRainfall.__table__.c.basin_id, BasinRainfall.__table__.c.ts],
        set_={
            "rainfall_mm": stmt.excluded.rainfall_mm,
            "source": stmt.excluded.source,
        },
    )
    result = session.execute(stmt)
    return result.rowcount or len(rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _normalize_hour(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.replace(minute=0, second=0, microsecond=0)


def ingest_hour(session: Session, ts: datetime, s3=None) -> HourStats:
    """Ingest a single hour's MRMS rainfall for all basins."""
    ts = _normalize_hour(ts)
    stat = HourStats(ts=ts)

    if s3 is None:
        s3 = _s3_client()

    key = find_key_for_hour(ts, s3=s3)
    if key is None:
        stat.status = "missing"
        stat.message = "no MRMS file published for this hour"
        return stat
    stat.s3_key = key

    basin_rows = _basin_rows(session)
    if not basin_rows:
        stat.status = "failed"
        stat.message = "no basins in DB; run basins.delineate first"
        return stat

    try:
        with _download_grib(key, s3=s3) as grib_path:
            da = _open_clipped(grib_path)
            means = compute_basin_means(da, basin_rows)
    except Exception as exc:  # noqa: BLE001
        logger.exception("MRMS ingest failed for %s (%s)", ts.isoformat(), key)
        stat.status = "failed"
        stat.message = f"{type(exc).__name__}: {exc}"
        return stat

    rows: list[dict] = []
    for basin_id, mm in means.items():
        if mm is None:
            continue
        rows.append(
            {
                "basin_id": basin_id,
                "ts": ts,
                "rainfall_mm": round(mm, 3),
                "source": "mrms_qpe_01h_pass2",
            }
        )

    stat.basins_updated = _upsert_rows(session, rows)
    session.commit()

    if rows:
        stat.rainfall_mm_mean = round(sum(r["rainfall_mm"] for r in rows) / len(rows), 3)
    stat.status = "ok"
    return stat


def ingest_backfill(
    session_factory,
    hours: int,
    concurrency: int = 4,
    end_ts: datetime | None = None,
) -> IngestStats:
    """Backfill the N most recent hours, skipping hours already present."""
    stats = IngestStats()
    end_ts = _normalize_hour(end_ts or datetime.now(timezone.utc))

    # One session per worker thread to avoid connection sharing.
    def _worker(ts: datetime) -> HourStats:
        s = session_factory()
        try:
            # Skip if every basin already has a row for this hour.
            with s.no_autoflush:
                present = s.execute(
                    select(func.count())
                    .select_from(BasinRainfall)
                    .where(BasinRainfall.ts == ts)
                ).scalar_one()
                total_basins = s.execute(
                    select(func.count()).select_from(Basin)
                ).scalar_one()
            if present >= total_basins and total_basins > 0:
                return HourStats(ts=ts, status="ok", message="already present", basins_updated=0)
            return ingest_hour(s, ts, s3=_s3_client())
        finally:
            s.close()

    targets = [end_ts - timedelta(hours=i) for i in range(hours)]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_worker, t): t for t in targets}
        for future in as_completed(futures):
            stat = future.result()
            stats.hours.append(stat)
            logger.info(
                "MRMS %s: %s (basins_updated=%d, mean=%s) %s",
                stat.ts.isoformat(),
                stat.status,
                stat.basins_updated,
                stat.rainfall_mm_mean,
                stat.message,
            )
    return stats


def ingest_once_job() -> None:
    """Scheduler entry point: ingest the most recent fully-published hour.

    MRMS publishes ~every 2 minutes with ~5-10 min latency. Ingesting
    the *previous* top-of-hour gives the file a chance to land.
    """
    settings = get_settings()
    if not settings.mrms_enabled:
        return
    session = SessionLocal()
    try:
        target = _normalize_hour(datetime.now(timezone.utc)) - timedelta(hours=1)
        stat = ingest_hour(session, target)
        logger.info(
            "Scheduled MRMS ingest %s: %s (basins_updated=%d)",
            stat.ts.isoformat(),
            stat.status,
            stat.basins_updated,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled MRMS ingest failed")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_hour(s: str) -> datetime:
    # Accept 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DD HH:MM'
    s = s.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    ts = datetime.fromisoformat(s)
    return _normalize_hour(ts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest MRMS hourly QPE into basin_rainfall")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--hour", type=_parse_hour, help="Specific UTC hour to ingest (e.g. 2026-04-16T14:00)")
    group.add_argument(
        "--backfill-hours",
        type=int,
        default=None,
        help="Backfill this many recent hours (e.g. 2160 for 90 days)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Thread pool size for --backfill-hours (default: 4)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # cfgrib is chatty
    logging.getLogger("cfgrib").setLevel(logging.WARNING)

    if args.backfill_hours is not None:
        stats = ingest_backfill(SessionLocal, hours=args.backfill_hours, concurrency=args.concurrency)
        summary = stats.summary()
        print(summary)
        return 0 if summary.get("failed", 0) == 0 else 1

    session = SessionLocal()
    try:
        target = args.hour if args.hour else _normalize_hour(datetime.now(timezone.utc)) - timedelta(hours=1)
        stat = ingest_hour(session, target)
        print(
            {
                "ts": stat.ts.isoformat(),
                "status": stat.status,
                "s3_key": stat.s3_key,
                "basins_updated": stat.basins_updated,
                "rainfall_mm_mean": stat.rainfall_mm_mean,
                "message": stat.message,
            }
        )
        return 0 if stat.status == "ok" else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
