"""Replace discontinued seed gauges with active Kickapoo mainstem stations.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-16

Migration 0002 seeded five gauges from README §4.1. Three of them
(05407470 Kickapoo at Ontario, 05408476 West Fork at Cashton,
05409000 West Fork near Readstown) were discontinued between 1939 and
2019 and return no data from NWIS. A fourth (05388250 Upper Iowa near
Dorchester) is in Iowa, outside the user's Wisconsin-only scope.

This migration hard-deletes those four gauges plus their streams and
seeds two currently-active Kickapoo mainstem replacements:

* 05407468 Kickapoo R @ Hwy 131 at Ontario, WI — direct successor to
  the old 05407470 gauge (same town, ~100m apart).
* 05410490 Kickapoo River at Steuben, WI — lower-mainstem Kickapoo,
  publishes turbidity.

05408000 Kickapoo at La Farge is left in place. FK CASCADE handles
removal of gauge_readings and stream_gauge_links when gauges and
streams are deleted.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DROPPED_GAUGE_IDS: tuple[str, ...] = (
    "05407470",
    "05408476",
    "05409000",
    "05388250",
)

DROPPED_STREAM_NAMES: tuple[str, ...] = (
    "Kickapoo River at Ontario",
    "West Fork Kickapoo at Cashton",
    "West Fork Kickapoo near Readstown",
    "Upper Iowa near Dorchester",
)

NEW_ROWS: tuple[tuple[str, str], ...] = (
    ("05407468", "Kickapoo River at Ontario"),
    ("05410490", "Kickapoo River at Steuben"),
)


def upgrade() -> None:
    bind = op.get_bind()

    # Order matters only for readability — FK CASCADE would handle either
    # direction. Delete streams first (cascades to stream_gauge_links),
    # then gauges (cascades to gauge_readings).
    bind.execute(
        sa.text("DELETE FROM streams WHERE name = ANY(:names)"),
        {"names": list(DROPPED_STREAM_NAMES)},
    )
    bind.execute(
        sa.text("DELETE FROM gauges WHERE usgs_site_id = ANY(:ids)"),
        {"ids": list(DROPPED_GAUGE_IDS)},
    )

    # Insert the two new Kickapoo stations.
    bind.execute(
        sa.text(
            """
            INSERT INTO gauges (usgs_site_id, name, parameters_available)
            VALUES (:site_id, :name, '{}'::jsonb)
            ON CONFLICT (usgs_site_id) DO NOTHING
            """
        ),
        [{"site_id": sid, "name": name} for sid, name in NEW_ROWS],
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO streams (name, is_watched)
            VALUES (:name, true)
            ON CONFLICT (name) DO NOTHING
            """
        ),
        [{"name": name} for _, name in NEW_ROWS],
    )
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
        [{"site_id": sid, "name": name} for sid, name in NEW_ROWS],
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Remove the two added seeds.
    new_ids = [sid for sid, _ in NEW_ROWS]
    new_names = [name for _, name in NEW_ROWS]
    bind.execute(
        sa.text("DELETE FROM streams WHERE name = ANY(:names)"),
        {"names": new_names},
    )
    bind.execute(
        sa.text("DELETE FROM gauges WHERE usgs_site_id = ANY(:ids)"),
        {"ids": new_ids},
    )

    # Restore the four originally seeded gauges + streams + links. This
    # mirrors migration 0002's upgrade for the dropped rows.
    restore_rows = (
        ("05407470", "Kickapoo River at Ontario"),
        ("05408476", "West Fork Kickapoo at Cashton"),
        ("05409000", "West Fork Kickapoo near Readstown"),
        ("05388250", "Upper Iowa near Dorchester"),
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO gauges (usgs_site_id, name, parameters_available)
            VALUES (:site_id, :name, '{}'::jsonb)
            ON CONFLICT (usgs_site_id) DO NOTHING
            """
        ),
        [{"site_id": sid, "name": name} for sid, name in restore_rows],
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO streams (name, is_watched)
            VALUES (:name, true)
            ON CONFLICT (name) DO NOTHING
            """
        ),
        [{"name": name} for _, name in restore_rows],
    )
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
        [{"site_id": sid, "name": name} for sid, name in restore_rows],
    )
