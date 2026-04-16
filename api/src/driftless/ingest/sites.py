"""Static configuration for USGS ingestion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedSite:
    site_id: str
    stream_name: str


# The five Driftless seed gauges named in README §4.1. Keep the order stable;
# Alembic migration 0002 seeds the same rows.
SEED_SITES: tuple[SeedSite, ...] = (
    SeedSite("05407470", "Kickapoo River at Ontario"),
    SeedSite("05408000", "Kickapoo River at La Farge"),
    SeedSite("05408476", "West Fork Kickapoo at Cashton"),
    SeedSite("05409000", "West Fork Kickapoo near Readstown"),
    SeedSite("05388250", "Upper Iowa near Dorchester"),
)


# USGS NWIS parameter codes we care about. See README §4.1.
# 00060 discharge (cfs), 00065 gauge height (ft), 00010 water temp (°C),
# 63680 turbidity (FNU) — not present at every station.
#
# Note: 63160 is NOT turbidity. It's "Stream water level elevation above
# NGVD 1929, in feet" — i.e. stage offset to a different datum. Several
# Driftless stations publish it but it's redundant with 00065 for our
# purposes, so we don't poll it.
PARAMETER_CODES: tuple[str, ...] = ("00060", "00065", "00010", "63680")


def seed_site_ids() -> list[str]:
    return [s.site_id for s in SEED_SITES]
