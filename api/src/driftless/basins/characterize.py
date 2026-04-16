"""Static basin characteristics: NLCD land cover, SSURGO soils, 3DEP slope.

For each delineated basin we compute:

* % land cover by broad class (row crop, forest, pasture, developed,
  wetland) — NLCD 2021 via ``pygeohydro.nlcd_bygeom``.
* Dominant hydrologic soil group — area-weighted from USDA Soil Data
  Access (SDA) REST. The ``gnatsgo-rasters`` collection on the Microsoft
  Planetary Computer doesn't expose HSG as a band; HSG only lives in
  SDA's tabular ``component`` table joined by mukey, so we query SDA
  directly.
* Average runoff curve number — pixel-wise NLCD lookup against the
  basin's dominant HSG via ``cn_lookup.py``. Approximates HSG as
  spatially uniform within the basin (the strongest HSG variability in
  the Driftless is captured by the dominant-class assignment anyway).
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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from shapely.geometry import MultiPolygon, shape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from driftless.basins.cn_lookup import cn_for
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
# Step 2: Hydrologic soil group (USDA Soil Data Access REST)
# ---------------------------------------------------------------------------


_SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/SDMTabularService/post.rest"

# 0.005° ≈ 500m — well below SSURGO mapunit polygon resolution and keeps
# the WKT POST body small enough for SDA's query length limit on basins
# up to a few thousand km².
_SDA_SIMPLIFY_TOLERANCE = 0.005


def _largest_polygon(geom):
    """SDA's ``with_WktWgs84`` helper expects a POLYGON, not a MULTIPOLYGON.
    Our delineated basins are single-part — strip the MULTIPOLYGON wrapper
    or pick the largest part if multi-part."""
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda g: g.area)
    return geom


def fetch_hsg_distribution(geom, timeout: int = 60) -> dict[str, float]:
    """Query USDA Soil Data Access for the area-weighted HSG distribution
    inside ``geom``. Returns ``{letter: pct}``; empty dict on no data.

    Uses the SDA spatial helper ``SDA_Get_Mukey_from_intersection_with_WktWgs84``
    to find map units intersecting the basin, joins to ``component``
    for ``hydgrpdcd``, and aggregates by component-percentage weight.
    Dual classes ('A/D','B/D','C/D') are reported as their drained
    letter ('A','B','C') for cleanliness — the NRCS CN table treats
    them this way too.

    SDA's REST endpoint accepts ``application/x-www-form-urlencoded``
    with ``format`` and ``query`` fields, not a JSON body.
    """
    poly = _largest_polygon(geom)
    poly_simple = poly.simplify(_SDA_SIMPLIFY_TOLERANCE, preserve_topology=True)
    wkt = poly_simple.wkt

    sql = (
        "SELECT co.hydgrpdcd AS hsg, SUM(co.comppct_r) AS weight "
        "FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('" + wkt + "') AS m "
        "INNER JOIN component co ON co.mukey = m.mukey "
        "WHERE co.majcompflag = 'Yes' AND co.hydgrpdcd IS NOT NULL "
        "GROUP BY co.hydgrpdcd"
    )
    body = urllib.parse.urlencode({"format": "JSON", "query": sql}).encode("utf-8")
    req = urllib.request.Request(
        _SDA_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Read error body so we can see SDA's actual complaint.
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:  # noqa: BLE001
            err_body = ""
        raise RuntimeError(
            f"SDA HTTP {exc.code}: {exc.reason} (wkt_chars={len(wkt)}, body_excerpt={err_body!r})"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SDA network error: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"SDA returned non-JSON: {raw_text[:200]!r}") from exc

    rows = payload.get("Table") or []
    if not rows:
        return {}

    raw: dict[str, float] = {}
    for row in rows:
        if not row or row[0] is None:
            continue
        letter_raw = str(row[0]).strip()
        # Skip a header row if SDA included one.
        if letter_raw.lower() in {"hsg", "hydgrpdcd"}:
            continue
        try:
            weight = float(row[1])
        except (TypeError, ValueError):
            continue
        letter = {"A/D": "A", "B/D": "B", "C/D": "C"}.get(letter_raw, letter_raw)
        raw[letter] = raw.get(letter, 0.0) + weight

    total = sum(raw.values())
    if total <= 0:
        return {}
    return {k: round(100.0 * v / total, 2) for k, v in raw.items()}


def dominant_letter(distribution: dict[str, float]) -> str | None:
    if not distribution:
        return None
    return max(distribution.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# Step 3: Runoff curve number
# ---------------------------------------------------------------------------


_LETTER_TO_HSG_CODE = {"A": 1, "B": 2, "C": 3, "D": 4}


def average_runoff_cn(nlcd_da, hsg_letter: str) -> float | None:
    """Per-pixel NLCD lookup averaged across the basin, treating the
    basin's dominant HSG as spatially uniform. This loses the modest
    HSG variation within most Driftless basins but is the right fidelity
    given that HSG comes from a basin-level SDA aggregate, not a raster.
    """
    hsg_code = _LETTER_TO_HSG_CODE.get(hsg_letter)
    if hsg_code is None:
        return None

    nlcd = np.asarray(nlcd_da.values).astype(int, copy=False)
    cn_accum = 0.0
    n = 0
    for code in np.unique(nlcd[nlcd > 0]):
        cn = cn_for(int(code), hsg_code)
        if cn is None:
            continue
        k = int((nlcd == code).sum())
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
    hsg_letter: str | None = None

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

    # HSG via SDA REST
    try:
        hsg_dist = fetch_hsg_distribution(geom)
        hsg_letter = dominant_letter(hsg_dist)
        if hsg_letter:
            fields["dominant_hsg"] = hsg_letter
            result.fields_written.append("dominant_hsg")
    except Exception as exc:  # noqa: BLE001
        logger.exception("HSG fetch failed for basin %d", basin.id)
        result.errors.append(f"hsg: {type(exc).__name__}: {exc}")

    # Runoff CN (requires both NLCD raster and a dominant HSG letter)
    if nlcd_da is not None and hsg_letter is not None:
        try:
            cn = average_runoff_cn(nlcd_da, hsg_letter)
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
