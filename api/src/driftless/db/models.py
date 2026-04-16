"""SQLAlchemy models.

Phase-1 schema per README §5, plus Phase-2 basin tables added in Chunk
2a (``basins``, ``basin_characteristics``, ``basin_rainfall``).

Notes:

* ``gauge_readings`` is a single regular table here. README §5 calls for
  monthly partitioning; that is deferred to a later Phase-2 chunk and
  will be introduced via a dedicated migration.
* ``stream_gauge_links`` is included because the watch-list query needs
  a stream↔gauge mapping; for Phase 1 every row has
  ``relationship='on_stream'``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from driftless.db.base import Base


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    waterbody_type: Mapped[str | None] = mapped_column(String(50))
    wi_dnr_class: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    is_watched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    links: Mapped[list["StreamGaugeLink"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan"
    )


class Gauge(Base):
    __tablename__ = "gauges"

    usgs_site_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    parameters_available: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    readings: Mapped[list["GaugeReading"]] = relationship(
        back_populates="gauge", cascade="all, delete-orphan"
    )
    links: Mapped[list["StreamGaugeLink"]] = relationship(
        back_populates="gauge", cascade="all, delete-orphan"
    )


class GaugeReading(Base):
    __tablename__ = "gauge_readings"

    gauge_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("gauges.usgs_site_id", ondelete="CASCADE"),
        primary_key=True,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    parameter_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric(14, 4))
    qualifier: Mapped[str | None] = mapped_column(String(20))

    gauge: Mapped[Gauge] = relationship(back_populates="readings")

    __table_args__ = (
        Index(
            "ix_gauge_readings_gauge_param_ts_desc",
            "gauge_id",
            "parameter_code",
            text("ts DESC"),
        ),
    )


class StreamGaugeLink(Base):
    __tablename__ = "stream_gauge_links"

    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), primary_key=True
    )
    usgs_site_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("gauges.usgs_site_id", ondelete="CASCADE"),
        primary_key=True,
    )
    relationship_kind: Mapped[str] = mapped_column(
        "relationship", String(20), nullable=False, server_default=text("'on_stream'")
    )
    distance_km: Mapped[float | None] = mapped_column(Numeric(8, 3))
    similarity_score: Mapped[float | None] = mapped_column(Numeric(5, 3))

    stream: Mapped[Stream] = relationship(back_populates="links")
    gauge: Mapped[Gauge] = relationship(back_populates="links")


# ---------------------------------------------------------------------------
# Phase 2 — basins
# ---------------------------------------------------------------------------


class Basin(Base):
    __tablename__ = "basins"

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    polygon = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    area_km2: Mapped[float | None] = mapped_column(Numeric(12, 3))
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'nldi_nwissite'")
    )
    source_site_id: Mapped[str | None] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    stream: Mapped[Stream] = relationship()
    characteristics: Mapped["BasinCharacteristics | None"] = relationship(
        back_populates="basin",
        cascade="all, delete-orphan",
        uselist=False,
    )
    rainfall: Mapped[list["BasinRainfall"]] = relationship(
        back_populates="basin", cascade="all, delete-orphan"
    )


class BasinCharacteristics(Base):
    __tablename__ = "basin_characteristics"

    basin_id: Mapped[int] = mapped_column(
        ForeignKey("basins.id", ondelete="CASCADE"), primary_key=True
    )
    pct_row_crop: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pct_forest: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pct_pasture: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pct_developed: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pct_wetland: Mapped[float | None] = mapped_column(Numeric(5, 2))
    baseflow_index: Mapped[float | None] = mapped_column(Numeric(5, 3))
    mean_slope: Mapped[float | None] = mapped_column(Numeric(7, 3))
    dominant_hsg: Mapped[str | None] = mapped_column(String(5))
    runoff_curve_number: Mapped[float | None] = mapped_column(Numeric(5, 2))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    basin: Mapped[Basin] = relationship(back_populates="characteristics")


class BasinRainfall(Base):
    __tablename__ = "basin_rainfall"

    basin_id: Mapped[int] = mapped_column(
        ForeignKey("basins.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    rainfall_mm: Mapped[float | None] = mapped_column(Numeric(8, 3))
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'mrms_qpe_01h_pass2'")
    )

    basin: Mapped[Basin] = relationship(back_populates="rainfall")

    __table_args__ = (
        Index("ix_basin_rainfall_basin_ts_desc", "basin_id", text("ts DESC")),
    )


# ---------------------------------------------------------------------------
# Phase 3 — projections
# ---------------------------------------------------------------------------


class Projection(Base):
    __tablename__ = "projections"

    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    clarity_class: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)

    stream: Mapped[Stream] = relationship()
