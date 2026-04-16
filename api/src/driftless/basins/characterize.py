"""Static basin characteristics: NLCD land cover, SSURGO/gNATSGO soils, 3DEP slope.

For each delineated basin we compute:

* % land cover by broad class (row crop, forest, pasture, developed,
  wetland) — NLCD 2021 via ``pygeohydro.nlcd_bygeom``.
* Dominant hydrologic soil group — gNATSGO ``hydclprs`` via
  ``pygeohydro.soil_gnatsgo``.
* Average runoff curve number — pixel-wise NLCD × HSG lookup from
  ``cn_lookup.py``.
* Mean slope (degrees) — 3DEP DEM via ``py3dep.get_map``, with a
  gradient-based slope computation.

Steps are independent: if any one fails we log and persist what did
succeed, leaving the rest of ``basin_characteristics`` NULL.

CLI::

    # Characterize every basin that doesn't yet have a characteristics row.
    python -m driftless.basins.characterize --all

    # Force re-compute for one basin.
    python -m driftless.basins.characterize --basin-id 3 --force
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from shapely.geometry import shape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from driftless.basins.cn_lookup import HSG_CODE_TO_LETTER, cn_for
from driftless.db.models import Basin, BasinCharacteristics
from driftless.db.session import SessionLocal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NLCD 2021 class groupings
# ---------------------------------------------------------------------------

NLCD_ROW_CROP = (82,)
NLCD_FOREST = (41, 42, 43)
NLCD_PASTURE = (81,)
NLCD_DEVELOPED = (21, 22, 23, 24)
NLCD_WETLAND = (90, 95)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CharacterizeResult:
    basin_id: int
    stream_id: int | None = None
    status: str = "pending"  # pending | created | updated | skipped | failed
    errors: list[str] = field(default_factory=list)
    fields_written: list[str] = field(default_factory=list)


@dataclass
class CharacterizeStats:
    results: list[CharacterizeResult] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
        for r in self.results:
            out[r.status] = out.get(r.status, 0) + 1
        return out


# ---------------------------------------------------------------------------
# Step 1: NLCD land cover
# ---------------------------------------------------------------------------


def fetch_nlcd_cover(geom):
    """Return an xarray DataArray of NLCD 2021 cover class clipped to geom."""
    import geopandas as gpd
    from pygeohydro import nlcd_bygeom

    gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
    result = nlcd_bygeom(gdf, years={"cover": [2021]}, resolution=30, crs=4326)
    # pygeohydro returns {index: Dataset}; grab the first
    first = next(iter(result.values()))
    # Dataset has a cover_2021 DataArray; rename can vary by version
    var_name = "cover_2021" if "cover_2021" in first.data_vars else next(iter(first.data_vars))
    return first[var_name]


def land_cover_percentages(da) -> dict[int, float]:
    """Given NLCD DataArray, return ``{class_code: pct}`` for all present classes."""
    values = np.asarray(da.values).flatten()
    values = values[~np.isnan(values.astype(float))] if values.dtype.kind == "f" else values
    values = values[values > 0]
    if values.size == 0:
        return {}
    total = values.size
    classes, counts = np.unique(values.astype(int), return_counts=True)
    return {int(c): round(100.0 * n / total, 2) for c, n in zip(classes, counts)}


def bucket_land_cover(pcts: dict[int, float]) -> dict[str, float]:
    def _sum(codes: Iterable[int]) -> float:
        return round(sum(pcts.get(c, 0.0) for c in codes), 2)

    return {
        "pct_row_crop": _sum(NLCD_ROW_CROP),
        "pct_forest": _sum(NLCD_FOREST),
        "pct_pasture": _sum(NLCD_PASTURE),
        "pct_developed": _sum(NLCD_DEVELOPED),
        "pct_wetland": _sum(NLCD_WETLAND),
    }


# ---------------------------------------------------------------------------
# Step 2: Hydrologic soil group (gNATSGO)
# ---------------------------------------------------------------------------


def fetch_hsg(geom):
    """Return an xarray DataArray of the gNATSGO hydrologic-group class.

    Pass the shapely geometry directly — feeding a GeoDataFrame triggers
    pygeohydro to call ``GeoDataFrame.bounds`` (which returns a per-row
    DataFrame), and pystac-client's bbox formatter can't flatten that to
    4 floats. A bare Polygon/MultiPolygon goes through ``geo2polygon``
    cleanly and ``.bounds`` returns a 4-tuple as expected.
    """
    from pygeohydro import soil_gnatsgo

    ds = soil_gnatsgo(["hydclprs"], geom, crs=4326)
    if hasattr(ds, "data_vars"):
        return ds["hydclprs"]
    # Some versions return a dict of datasets keyed by basin index.
    first = next(iter(ds.values()))
    return first["hydclprs"]


def dominant_hsg_letter(da) -> tuple[str | None, dict[str, float]]:
    """Return (dominant letter, {letter: pct}) from a gNATSGO hydclprs raster."""
    values = np.asarray(da.values).flatten()
    values = values[~np.isnan(values.astype(float))] if values.dtype.kind == "f" else values
    values = values[values > 0]
    if values.size == 0:
        return None, {}
    pcts: dict[str, float] = {}
    classes, counts = np.unique(values.astype(int), return_counts=True)
    total = values.size
    for code, n in zip(classes, counts):
        letter = HSG_CODE_TO_LETTER.get(int(code))
        if letter is None:
            continue
        pcts[letter] = round(pcts.get(letter, 0.0) + 100.0 * n / total, 2)
    if not pcts:
        return None, {}
    dominant = max(pcts.items(), key=lambda kv: kv[1])[0]
    return dominant, pcts


# ---------------------------------------------------------------------------
# Step 3: Runoff curve number
# ---------------------------------------------------------------------------


def average_runoff_cn(nlcd_da, hsg_da) -> float | None:
    """Pixel-wise NLCD × HSG lookup averaged across the basin.

    Reprojects the HSG raster to match NLCD's grid so we can pair cells
    deterministically. Returns None if nothing resolvable overlaps.
    """
    try:
        hsg_matched = hsg_da.rio.reproject_match(nlcd_da)
    except Exception as exc:  # noqa: BLE001
        logger.debug("HSG reproject failed: %s", exc)
        return None

    nlcd = np.asarray(nlcd_da.values).astype(int, copy=False)
    hsg = np.asarray(hsg_matched.values).astype(int, copy=False)
    if nlcd.shape != hsg.shape:
        return None

    cn_accum = 0.0
    n = 0
    nlcd_codes = np.unique(nlcd[nlcd > 0])
    hsg_codes = np.unique(hsg[hsg > 0])
    for nc in nlcd_codes:
        for hc in hsg_codes:
            cn = cn_for(int(nc), int(hc))
            if cn is None:
                continue
            mask = (nlcd == nc) & (hsg == hc)
            k = int(mask.sum())
            if k == 0:
                continue
            cn_accum += cn * k
            n += k
    if n == 0:
        return None
    return round(cn_accum / n, 2)


# ---------------------------------------------------------------------------
# Step 4: Mean slope
# ---------------------------------------------------------------------------


def compute_mean_slope_degrees(geom) -> float | None:
    """3DEP 30m DEM-based mean slope within the basin polygon."""
    import py3dep

    dem = py3dep.get_map("DEM", geom, resolution=30, geo_crs=4326, crs=5070)
    # py3dep returns an xarray DataArray in CRS 5070 (Albers equal-area).
    # Pixel size is ~30 m in both directions.
    arr = np.asarray(dem.values).astype(float)
    arr = np.where(arr <= -1e30, np.nan, arr)
    if np.all(np.isnan(arr)):
        return None
    # pixel spacing in metres from the transform
    try:
        transform = dem.rio.transform()
        dx = abs(transform.a)
        dy = abs(transform.e)
    except Exception:  # noqa: BLE001
        dx = dy = 30.0
    # numpy.gradient: returns (dz/dy, dz/dx) for 2D input
    gy, gx = np.gradient(arr, dy, dx)
    slope_rad = np.arctan(np.sqrt(gx**2 + gy**2))
    return round(float(np.degrees(np.nanmean(slope_rad))), 3)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _basin_geometry(session: Session, basin_id: int):
    geojson_str = session.scalar(
        select(func.ST_AsGeoJSON(Basin.polygon)).where(Basin.id == basin_id)
    )
    if geojson_str is None:
        return None
    return shape(json.loads(geojson_str))


def _upsert(session: Session, basin_id: int, fields: dict) -> str:
    existing = session.scalar(
        select(BasinCharacteristics).where(BasinCharacteristics.basin_id == basin_id)
    )
    if existing is None:
        session.add(BasinCharacteristics(basin_id=basin_id, **fields))
        return "created"
    for k, v in fields.items():
        setattr(existing, k, v)
    return "updated"


def characterize_basin(
    session: Session, basin: Basin, force: bool = False
) -> CharacterizeResult:
    result = CharacterizeResult(basin_id=basin.id, stream_id=basin.stream_id)

    existing = session.scalar(
        select(BasinCharacteristics).where(BasinCharacteristics.basin_id == basin.id)
    )
    if existing is not None and not force:
        result.status = "skipped"
        return result

    geom = _basin_geometry(session, basin.id)
    if geom is None:
        result.status = "failed"
        result.errors.append("basin has no polygon")
        return result

    fields: dict = {}
    nlcd_da = None
    hsg_da = None

    # Land cover
    try:
        nlcd_da = fetch_nlcd_cover(geom)
        pcts = land_cover_percentages(nlcd_da)
        fields.update(bucket_land_cover(pcts))
        result.fields_written.extend(
            ["pct_row_crop", "pct_forest", "pct_pasture", "pct_developed", "pct_wetland"]
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("NLCD fetch failed for basin %d", basin.id)
        result.errors.append(f"nlcd: {type(exc).__name__}: {exc}")

    # HSG
    try:
        hsg_da = fetch_hsg(geom)
        letter, _ = dominant_hsg_letter(hsg_da)
        if letter:
            fields["dominant_hsg"] = letter
            result.fields_written.append("dominant_hsg")
    except Exception as exc:  # noqa: BLE001
        logger.exception("HSG fetch failed for basin %d", basin.id)
        result.errors.append(f"hsg: {type(exc).__name__}: {exc}")

    # Runoff CN (requires both)
    if nlcd_da is not None and hsg_da is not None:
        try:
            cn = average_runoff_cn(nlcd_da, hsg_da)
            if cn is not None:
                fields["runoff_curve_number"] = cn
                result.fields_written.append("runoff_curve_number")
        except Exception as exc:  # noqa: BLE001
            logger.exception("CN computation failed for basin %d", basin.id)
            result.errors.append(f"cn: {type(exc).__name__}: {exc}")

    # Mean slope
    try:
        slope = compute_mean_slope_degrees(geom)
        if slope is not None:
            fields["mean_slope"] = slope
            result.fields_written.append("mean_slope")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Slope computation failed for basin %d", basin.id)
        result.errors.append(f"slope: {type(exc).__name__}: {exc}")

    if not fields:
        result.status = "failed"
        return result

    status = _upsert(session, basin.id, fields)
    session.commit()
    result.status = status
    return result


def characterize_all(
    session: Session,
    basin_ids: Iterable[int] | None = None,
    force: bool = False,
) -> CharacterizeStats:
    stmt = select(Basin).order_by(Basin.id)
    if basin_ids is not None:
        stmt = stmt.where(Basin.id.in_(list(basin_ids)))

    stats = CharacterizeStats()
    for basin in session.scalars(stmt):
        res = characterize_basin(session, basin, force=force)
        stats.results.append(res)
        logger.info(
            "Basin %d: %s (wrote %s) errors=%s",
            res.basin_id,
            res.status,
            res.fields_written,
            res.errors,
        )
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute static basin characteristics: NLCD land cover, gNATSGO HSG, runoff CN, slope"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Characterize every basin (default)")
    group.add_argument(
        "--basin-id",
        type=int,
        action="append",
        dest="basin_ids",
        help="Characterize a specific basin by id (repeatable)",
    )
    parser.add_argument("--force", action="store_true", help="Re-compute and overwrite")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # pygeohydro/py3dep are chatty at DEBUG
    for name in ("pygeohydro", "py3dep", "async_retriever", "aiohttp_client_cache"):
        logging.getLogger(name).setLevel(logging.WARNING)

    session = SessionLocal()
    try:
        stats = characterize_all(
            session,
            basin_ids=args.basin_ids,
            force=args.force,
        )
    finally:
        session.close()

    summary = stats.summary()
    print(summary)
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
