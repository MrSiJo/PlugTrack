"""Distance + currency formatting helpers (server-side).

The frontend handles most display formatting (`frontend/src/utils/`),
but a handful of API responses include pre-formatted strings (e.g.
debug dumps, CLI exports) — those go through these helpers.
"""
from __future__ import annotations

_KM_PER_MILE = 1.609344


def km_to_mi(km: float) -> float:
    """Convert kilometres to miles."""
    return km / _KM_PER_MILE


def mi_to_km(mi: float) -> float:
    """Convert miles to kilometres."""
    return mi * _KM_PER_MILE


def format_distance(km: float, unit: str) -> str:
    """Render `km` in the requested display unit (`'mi'` or `'km'`)."""
    if unit == "km":
        value = km
    else:
        value = km_to_mi(km)
    return f"{round(value)} {unit}"
