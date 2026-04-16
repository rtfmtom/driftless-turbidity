"""Create Phase 2 basin tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-16

Adds the three Phase-2 tables for basin polygons, static basin
characteristics, and hourly per-basin rainfall (README §5). Only
`basins` is populated in Chunk 2a; `basin_characteristics` and
`basin_rainfall` get their first rows in Chunks 2b/2c.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "basins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "stream_id",
            sa.Integer(),
            sa.ForeignKey("streams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "polygon",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326),
            nullable=False,
        ),
        sa.Column("area_km2", sa.Numeric(12, 3)),
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'nldi_nwissite'"),
        ),
        sa.Column("source_site_id", sa.String(length=20)),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("stream_id", name="uq_basins_stream_id"),
    )
    op.create_index("ix_basins_stream_id", "basins", ["stream_id"])

    op.create_table(
        "basin_characteristics",
        sa.Column(
            "basin_id",
            sa.Integer(),
            sa.ForeignKey("basins.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("pct_row_crop", sa.Numeric(5, 2)),
        sa.Column("pct_forest", sa.Numeric(5, 2)),
        sa.Column("pct_pasture", sa.Numeric(5, 2)),
        sa.Column("pct_developed", sa.Numeric(5, 2)),
        sa.Column("pct_wetland", sa.Numeric(5, 2)),
        sa.Column("baseflow_index", sa.Numeric(5, 3)),
        sa.Column("mean_slope", sa.Numeric(7, 3)),
        sa.Column("dominant_hsg", sa.String(length=5)),
        sa.Column("runoff_curve_number", sa.Numeric(5, 2)),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "basin_rainfall",
        sa.Column(
            "basin_id",
            sa.Integer(),
            sa.ForeignKey("basins.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("rainfall_mm", sa.Numeric(8, 3)),
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'mrms_qpe_01h_pass2'"),
        ),
    )
    op.create_index(
        "ix_basin_rainfall_basin_ts_desc",
        "basin_rainfall",
        ["basin_id", sa.text("ts DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_basin_rainfall_basin_ts_desc", table_name="basin_rainfall")
    op.drop_table("basin_rainfall")
    op.drop_table("basin_characteristics")
    op.drop_index("ix_basins_stream_id", table_name="basins")
    op.drop_table("basins")
