"""Seed Phase 1 streams, gauges, and on-stream links.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-16

Populates the five Driftless-area USGS gauges named in README §4.1 along
with a 1:1 Stream and an ``on_stream`` StreamGaugeLink per gauge. Location
and parameters_available are backfilled by the USGS ingest job on first
run, so they are left as NULL/{} here.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS: tuple[tuple[str, str], ...] = (
    ("05407470", "Kickapoo River at Ontario"),
    ("05408000", "Kickapoo River at La Farge"),
    ("05408476", "West Fork Kickapoo at Cashton"),
    ("05409000", "West Fork Kickapoo near Readstown"),
    ("05388250", "Upper Iowa near Dorchester"),
)


def upgrade() -> None:
    bind = op.get_bind()

    # Gauges
    bind.execute(
        sa.text(
            """
            INSERT INTO gauges (usgs_site_id, name, parameters_available)
            VALUES (:site_id, :name, '{}'::jsonb)
            ON CONFLICT (usgs_site_id) DO NOTHING
            """
        ),
        [{"site_id": sid, "name": name} for sid, name in SEED_ROWS],
    )

    # Streams
    bind.execute(
        sa.text(
            """
            INSERT INTO streams (name, is_watched)
            VALUES (:name, true)
            ON CONFLICT (name) DO NOTHING
            """
        ),
        [{"name": name} for _, name in SEED_ROWS],
    )

    # Links (stream name == gauge name in Phase 1)
    bind.execute(
        sa.text(
            """
            INSERT INTO stream_gauge_links (stream_id, usgs_site_id, relationship)
            SELECT s.id, :site_id, 'on_stream'
            FROM streams s
            WHERE s.name = :name
            ON CONFLICT (stream_id, usgs_site_id) DO NOTHING
            """
        ),
        [{"site_id": sid, "name": name} for sid, name in SEED_ROWS],
    )


def downgrade() -> None:
    bind = op.get_bind()
    site_ids = [sid for sid, _ in SEED_ROWS]
    names = [name for _, name in SEED_ROWS]

    bind.execute(
        sa.text(
            "DELETE FROM stream_gauge_links WHERE usgs_site_id = ANY(:site_ids)"
        ),
        {"site_ids": site_ids},
    )
    bind.execute(
        sa.text("DELETE FROM gauge_readings WHERE gauge_id = ANY(:site_ids)"),
        {"site_ids": site_ids},
    )
    bind.execute(
        sa.text("DELETE FROM gauges WHERE usgs_site_id = ANY(:site_ids)"),
        {"site_ids": site_ids},
    )
    bind.execute(
        sa.text("DELETE FROM streams WHERE name = ANY(:names)"),
        {"names": names},
    )
