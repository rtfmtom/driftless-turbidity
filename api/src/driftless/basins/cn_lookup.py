"""NRCS runoff curve number lookup.

Average CN values by (NLCD 2021 land-cover class) × (hydrologic soil
group), from NRCS TR-55 Table 2-2a and common engineering references.
For dual-class HSGs (A/D, B/D, C/D), drained and undrained behave
differently; we use the drained ("better") class as the default, which
is optimistic but standard for CN calcs on Driftless farmland.

HSG codes match gNATSGO ``hydclprs``:
    1=A, 2=B, 3=C, 4=D, 5=A/D, 6=B/D, 7=C/D
"""

from __future__ import annotations

HSG_CODE_TO_LETTER = {
    1: "A",
    2: "B",
    3: "C",
    4: "D",
    5: "A/D",
    6: "B/D",
    7: "C/D",
}

# For dual classes we treat them as the drained (better-drainage) letter.
HSG_EFFECTIVE = {
    1: "A",
    2: "B",
    3: "C",
    4: "D",
    5: "A",
    6: "B",
    7: "C",
}

# NLCD class code → {HSG letter → CN}. Values: NRCS TR-55 medium
# condition / "fair" hydrologic condition typical for the Driftless.
_CN: dict[int, dict[str, int]] = {
    # Open Water — impervious-equivalent
    11: {"A": 100, "B": 100, "C": 100, "D": 100},
    # Perennial Ice/Snow (rare in Driftless)
    12: {"A": 98,  "B": 98,  "C": 98,  "D": 98},
    # Developed
    21: {"A": 49,  "B": 69,  "C": 79,  "D": 84},  # Open Space
    22: {"A": 57,  "B": 72,  "C": 81,  "D": 86},  # Low Intensity
    23: {"A": 61,  "B": 75,  "C": 83,  "D": 87},  # Medium Intensity
    24: {"A": 77,  "B": 85,  "C": 90,  "D": 92},  # High Intensity
    # Barren
    31: {"A": 77,  "B": 86,  "C": 91,  "D": 94},
    # Forest
    41: {"A": 36,  "B": 60,  "C": 73,  "D": 79},  # Deciduous
    42: {"A": 36,  "B": 60,  "C": 73,  "D": 79},  # Evergreen
    43: {"A": 36,  "B": 60,  "C": 73,  "D": 79},  # Mixed
    # Shrub
    52: {"A": 35,  "B": 56,  "C": 70,  "D": 77},
    # Grassland
    71: {"A": 49,  "B": 69,  "C": 79,  "D": 84},
    # Pasture/Hay
    81: {"A": 49,  "B": 69,  "C": 79,  "D": 84},
    # Cultivated Crops (row crop) — straight row, good condition
    82: {"A": 67,  "B": 78,  "C": 85,  "D": 89},
    # Woody Wetlands
    90: {"A": 98,  "B": 98,  "C": 98,  "D": 98},
    # Emergent Herbaceous Wetlands
    95: {"A": 98,  "B": 98,  "C": 98,  "D": 98},
}


def cn_for(nlcd: int, hsg_code: int) -> int | None:
    """Lookup curve number for a (NLCD, HSG) pair. Returns None if unknown."""
    entry = _CN.get(int(nlcd))
    if entry is None:
        return None
    letter = HSG_EFFECTIVE.get(int(hsg_code))
    if letter is None:
        return None
    return entry.get(letter)
