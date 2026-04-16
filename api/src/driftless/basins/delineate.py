"""Basin delineation via NHDPlus/NLDI.

For a watched stream, we take its on-stream USGS gauge, hand the site id
to NLDI's ``get_basins`` service, and receive back the polygon of the
upstream drainage basin. That polygon is stored as MULTIPOLYGON in
``basins.polygon`` and its area as ``basins.area_km2``.

CLI::

    # Delineate all watched streams that don't yet have a basin.
    python -m driftless.basins.delineate --all-watched

    # Re-delineate a specific stream, overwriting any existing basin.
    python -m driftless.basins.delineate --stream-id 3 --force

Phase 2a focuses on the primary NLDI-by-site path (every current seed
has a USGS gauge). DEM-based pour-point delineation via ``py3dep`` is a
later chunk — when a stream with no gauge needs a basin.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from typing import Iterable

from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.orm import Session

from driftless.db.models import Basin, Gauge, Stream, StreamGaugeLink
from driftless.db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass
class DelineateResult:
    stream_id: int
    stream_name: str
    site_id: str | None
    status: str  # 'created' | 'updated' | 'skipped' | 'failed'
    area_km2: float | None = None
    message: str = ""


@dataclass
class DelineateStats:
    results: list[DelineateResult] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
        for r in self.results:
            out[r.status] = out.get(r.status, 0) + 1
        return out


# ---------------------------------------------------------------------------
# NLDI access
# ---------------------------------------------------------------------------


def fetch_basin_for_site(site_id: str):
    """Return a GeoDataFrame with one row — the NLDI basin draining to the
    given USGS site — or None if NLDI has no basin for it.

    pynhd wraps the NLDI REST service. We set ``simplified=True`` so the
    returned polygon is already decimated (fewer vertices, faster Postgres
    writes and smaller GeoJSON payloads). That loses some edge precision;
    for a clarity dashboard that's fine.
    """
    from pynhd import NLDI  # local import keeps module-level cost low

    nldi = NLDI()
    gdf = nldi.get_basins([site_id], fsource="nwissite", split_catchment=False, simplified=True)
    if gdf is None or gdf.empty:
        return None
    return gdf


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _to_multipolygon(geom: BaseGeometry) -> MultiPolygon:
    """Normalize a Polygon or MultiPolygon into a MultiPolygon."""
    if geom.is_empty:
        raise ValueError("empty geometry returned by NLDI")
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    # GeometryCollection or other — try unioning into a single shape.
    merged = unary_union(geom)
    if isinstance(merged, Polygon):
        return MultiPolygon([merged])
    if isinstance(merged, MultiPolygon):
        return merged
    raise ValueError(f"unexpected geometry type from NLDI: {geom.geom_type}")


def _area_km2(geom_wgs84: BaseGeometry) -> float:
    """Compute area in km² using an equal-area projection.

    Using ``pyproj`` with an Albers Equal Area projection centered on
    the Driftless region (43°N, -91°W). Good enough to ~0.1% for basins
    of a few thousand km².
    """
    import pyproj
    from shapely.ops import transform

    project = pyproj.Transformer.from_crs(
        "EPSG:4326",
        "+proj=aea +lat_1=42 +lat_2=45 +lat_0=43.5 +lon_0=-91 +datum=WGS84 +units=m +no_defs",
        always_xy=True,
    ).transform
    projected = transform(project, geom_wgs84)
    return projected.area / 1_000_000.0


# ---------------------------------------------------------------------------
# Per-stream delineation
# ---------------------------------------------------------------------------


def _on_stream_gauge(session: Session, stream_id: int) -> Gauge | None:
    """Return the first on-stream gauge linked to the stream, if any."""
    return session.scalar(
        select(Gauge)
        .join(StreamGaugeLink, StreamGaugeLink.usgs_site_id == Gauge.usgs_site_id)
        .where(
            StreamGaugeLink.stream_id == stream_id,
            StreamGaugeLink.relationship_kind == "on_stream",
        )
        .order_by(Gauge.usgs_site_id)
        .limit(1)
    )


def delineate_stream(
    session: Session, stream: Stream, force: bool = False
) -> DelineateResult:
    existing = session.scalar(select(Basin).where(Basin.stream_id == stream.id))
    if existing is not None and not force:
        return DelineateResult(
            stream_id=stream.id,
            stream_name=stream.name,
            site_id=existing.source_site_id,
            status="skipped",
            area_km2=float(existing.area_km2) if existing.area_km2 is not None else None,
            message="basin already exists; pass --force to overwrite",
        )

    gauge = _on_stream_gauge(session, stream.id)
    if gauge is None:
        return DelineateResult(
            stream_id=stream.id,
            stream_name=stream.name,
            site_id=None,
            status="failed",
            message="no on-stream USGS gauge linked; manual pour-point not yet supported",
        )

    try:
        gdf = fetch_basin_for_site(gauge.usgs_site_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("NLDI basin fetch failed for %s", gauge.usgs_site_id)
        return DelineateResult(
            stream_id=stream.id,
            stream_name=stream.name,
            site_id=gauge.usgs_site_id,
            status="failed",
            message=f"NLDI fetch error: {exc}",
        )

    if gdf is None or gdf.empty:
        return DelineateResult(
            stream_id=stream.id,
            stream_name=stream.name,
            site_id=gauge.usgs_site_id,
            status="failed",
            message="NLDI returned no basin for this site",
        )

    try:
        geom = _to_multipolygon(gdf.geometry.iloc[0])
    except ValueError as exc:
        return DelineateResult(
            stream_id=stream.id,
            stream_name=stream.name,
            site_id=gauge.usgs_site_id,
            status="failed",
            message=str(exc),
        )

    area_km2 = _area_km2(geom)
    wkt = f"SRID=4326;{geom.wkt}"

    if existing is None:
        basin = Basin(
            stream_id=stream.id,
            polygon=wkt,
            area_km2=area_km2,
            source="nldi_nwissite",
            source_site_id=gauge.usgs_site_id,
        )
        session.add(basin)
        status = "created"
    else:
        existing.polygon = wkt
        existing.area_km2 = area_km2
        existing.source = "nldi_nwissite"
        existing.source_site_id = gauge.usgs_site_id
        status = "updated"

    session.flush()
    return DelineateResult(
        stream_id=stream.id,
        stream_name=stream.name,
        site_id=gauge.usgs_site_id,
        status=status,
        area_km2=area_km2,
    )


def delineate_all(
    session: Session,
    stream_ids: Iterable[int] | None = None,
    force: bool = False,
    only_watched: bool = True,
) -> DelineateStats:
    stmt = select(Stream)
    if stream_ids is not None:
        stmt = stmt.where(Stream.id.in_(list(stream_ids)))
    elif only_watched:
        stmt = stmt.where(Stream.is_watched.is_(True))
    stmt = stmt.order_by(Stream.id)

    stats = DelineateStats()
    for stream in session.scalars(stmt):
        result = delineate_stream(session, stream, force=force)
        stats.results.append(result)
        if result.status in {"created", "updated"}:
            session.commit()
            logger.info(
                "Delineated %s (site %s): %.1f km² [%s]",
                result.stream_name,
                result.site_id,
                result.area_km2 or 0.0,
                result.status,
            )
        else:
            session.rollback()
            logger.info(
                "Skipped %s: %s (%s)",
                result.stream_name,
                result.status,
                result.message,
            )

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delineate basins for watched streams via NLDI")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all-watched",
        action="store_true",
        help="Delineate every watched stream missing a basin (default when no flag given)",
    )
    group.add_argument(
        "--stream-id",
        type=int,
        action="append",
        dest="stream_ids",
        help="Delineate a specific stream by id (repeatable)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-delineate and overwrite even if a basin row already exists",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    session = SessionLocal()
    try:
        if args.stream_ids:
            stats = delineate_all(session, stream_ids=args.stream_ids, force=args.force)
        else:
            stats = delineate_all(session, force=args.force)
    finally:
        session.close()

    summary = stats.summary()
    print(summary)
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
