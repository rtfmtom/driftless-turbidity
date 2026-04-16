"""Enable PostGIS and create Phase 1 core tables.

Revision ID: 0001
Revises:
Create Date: 2026-04-16

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("waterbody_type", sa.String(length=50)),
        sa.Column("wi_dnr_class", sa.String(length=20)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "is_watched",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_streams_name"),
    )

    op.create_table(
        "gauges",
        sa.Column("usgs_site_id", sa.String(length=20), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("location", Geometry(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column(
            "parameters_available",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "gauge_readings",
        sa.Column(
            "gauge_id",
            sa.String(length=20),
            sa.ForeignKey("gauges.usgs_site_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("parameter_code", sa.String(length=10), primary_key=True),
        sa.Column("value", sa.Numeric(14, 4)),
        sa.Column("qualifier", sa.String(length=20)),
    )
    op.create_index(
        "ix_gauge_readings_gauge_param_ts_desc",
        "gauge_readings",
        ["gauge_id", "parameter_code", sa.text("ts DESC")],
    )

    op.create_table(
        "stream_gauge_links",
        sa.Column(
            "stream_id",
            sa.Integer(),
            sa.ForeignKey("streams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "usgs_site_id",
            sa.String(length=20),
            sa.ForeignKey("gauges.usgs_site_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "relationship",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'on_stream'"),
        ),
        sa.Column("distance_km", sa.Numeric(8, 3)),
        sa.Column("similarity_score", sa.Numeric(5, 3)),
    )


def downgrade() -> None:
    op.drop_table("stream_gauge_links")
    op.drop_index("ix_gauge_readings_gauge_param_ts_desc", table_name="gauge_readings")
    op.drop_table("gauge_readings")
    op.drop_table("gauges")
    op.drop_table("streams")
    # Intentionally do NOT drop the postgis extension; other schemas may use it.
