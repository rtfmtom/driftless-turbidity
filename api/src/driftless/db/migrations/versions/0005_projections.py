"""Create the projections table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16

Adds the Phase-3 ``projections`` table from README §5. One row per
hourly heuristic projection per stream, keeping a JSONB
``feature_snapshot`` so the UI can show the user *why* the model
called the water clear/tinged/stained/blown (per README §10 "Model
honesty").
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projections",
        sa.Column(
            "stream_id",
            sa.Integer(),
            sa.ForeignKey("streams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            primary_key=True,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clarity_class", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column(
            "feature_snapshot",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.CheckConstraint(
            "clarity_class IN ('clear','tinged','stained','blown')",
            name="ck_projections_clarity_class",
        ),
        sa.CheckConstraint(
            "confidence IN ('low','medium','high')",
            name="ck_projections_confidence",
        ),
    )
    # Latest-per-stream lookups dominate; index by (stream_id, computed_at desc).
    op.create_index(
        "ix_projections_stream_computed_desc",
        "projections",
        ["stream_id", sa.text("computed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_projections_stream_computed_desc", table_name="projections")
    op.drop_table("projections")
