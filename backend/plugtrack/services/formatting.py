"""Distance + currency formatting helpers (server-side).

The frontend handles most display formatting (`frontend/src/utils/`),
but a handful of API responses include pre-formatted strings (e.g.
debug dumps, CLI exports) — those go through these helpers.
"""

from __future__ import annotations

# Single source of truth for the km<->mi factor (PLUG-L4).
KM_PER_MILE = 1.609344

_CURRENCY_SYMBOLS: dict[str, str] = {
    "GBP": "£",
    "EUR": "€",
    "USD": "$",
}


def km_to_mi(km: float) -> float:
    """Convert kilometres to miles."""
    return km / KM_PER_MILE


def mi_to_km(mi: float) -> float:
    """Convert miles to kilometres."""
    return mi * KM_PER_MILE


def format_distance(km: float, unit: str) -> str:
    """Render `km` in the requested display unit (`'mi'` or `'km'`)."""
    if unit == "km":
        value = km
    else:
        value = km_to_mi(km)
    return f"{round(value)} {unit}"


def format_currency(pence: int, currency: str = "GBP") -> str:
    """Format a pence integer as a human-readable currency string.

    Examples::

        format_currency(4210)          -> "£42.10"
        format_currency(0)             -> "£0.00"
        format_currency(4210, "EUR")   -> "€42.10"
        format_currency(4210, "USD")   -> "$42.10"
        format_currency(4210, "JPY")   -> "42.10"  # unknown currency, no symbol
    """
    symbol = _CURRENCY_SYMBOLS.get(currency, "")
    return f"{symbol}{pence / 100:.2f}"
