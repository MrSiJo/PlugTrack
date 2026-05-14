"""Cost computation per the precedence rule in spec §3.3 lines 143–162.

The rule (verbatim from the spec):

    if total_cost_pence_override is not None:
        cost_pence = total_cost_pence_override
        cost_basis = 'override_total'
    elif cost_per_kwh_override_p is not None:
        cost_pence = round(kwh_added * cost_per_kwh_override_p)
        cost_basis = 'override_per_kwh'
        tariff_p_per_kwh = cost_per_kwh_override_p
    elif location.is_free:
        cost_pence = 0
        cost_basis = 'location_free'
        tariff_p_per_kwh = 0
    elif location.default_cost_per_kwh_p is not None:
        cost_pence = round(kwh_added * location.default_cost_per_kwh_p)
        cost_basis = 'location_rate'
        tariff_p_per_kwh = location.default_cost_per_kwh_p
    else:
        cost_pence = round(kwh_added * settings.default_home_rate_p_per_kwh)
        cost_basis = 'home_rate'
        tariff_p_per_kwh = settings.default_home_rate_p_per_kwh

Mixed override case: when BOTH overrides are present we follow the
spec — `total_cost_pence_override` wins (sets `cost_pence` and
`cost_basis='override_total'`), but we PRESERVE
`cost_per_kwh_override_p` as the returned `tariff_p_per_kwh` so the
SessionDetail breakdown widget can show "rate × kWh + £x fees".

Total-only override: when only `total_cost_pence_override` is set we
DERIVE `tariff_p_per_kwh = total / kwh_added` (rounded to 2dp) so the
effective rate is surfaced to the user. Public chargers often only
print the total on the receipt, and this lets PlugTrack still answer
"what did I pay per kWh" without the user having to do the maths.
Returns `None` when `kwh_added == 0` to avoid division by zero.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from ..models.location import Location


class SessionOverrides(TypedDict, total=False):
    cost_per_kwh_override_p: Optional[float]
    total_cost_pence_override: Optional[int]


def compute_session_cost(
    kwh_added: float,
    location: Optional[Location],
    session_overrides: SessionOverrides,
    settings_default_home_rate_p_per_kwh: float,
) -> tuple[Optional[int], str, Optional[float]]:
    """Apply the cost-precedence rule.

    Returns `(cost_pence, cost_basis, tariff_p_per_kwh)`. `cost_pence`
    is rounded to integer pence. `tariff_p_per_kwh` is the per-kWh rate
    that produced the cost — preserved for breakdown display even in
    the mixed-override case.
    """
    total_override = session_overrides.get("total_cost_pence_override")
    per_kwh_override = session_overrides.get("cost_per_kwh_override_p")

    # Total wins for `cost_pence` / `cost_basis`. Tariff resolution:
    #   - per-kWh override given too → use that (mixed-override case).
    #   - else → derive from the total (effective p/kWh display).
    #   - kwh_added is zero → None to avoid division-by-zero.
    if total_override is not None:
        if per_kwh_override is not None:
            tariff_for_breakdown: Optional[float] = float(per_kwh_override)
        elif kwh_added > 0:
            tariff_for_breakdown = round(float(total_override) / float(kwh_added), 2)
        else:
            tariff_for_breakdown = None
        return int(total_override), "override_total", tariff_for_breakdown

    if per_kwh_override is not None:
        rate = float(per_kwh_override)
        return round(kwh_added * rate), "override_per_kwh", rate

    if location is not None and location.is_free:
        return 0, "location_free", 0.0

    if location is not None and location.default_cost_per_kwh_p is not None:
        rate = float(location.default_cost_per_kwh_p)
        return round(kwh_added * rate), "location_rate", rate

    rate = float(settings_default_home_rate_p_per_kwh)
    return round(kwh_added * rate), "home_rate", rate
