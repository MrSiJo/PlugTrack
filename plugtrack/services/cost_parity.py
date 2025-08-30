# services/cost_parity.py
from typing import Optional

def petrol_ppm(p_per_litre: float, mpg_uk: float) -> Optional[float]:
    """
    Petrol cost per mile (pence per mile, p/mi).
    UK MPG and petrol price in pence per litre.
    ppm = (p/L * 4.54609) / MPG
    Returns None if inputs invalid.
    """
    try:
        if p_per_litre <= 0 or mpg_uk <= 0:
            return None
        litres_per_gallon = 4.54609
        pence_per_gallon = p_per_litre * litres_per_gallon
        return pence_per_gallon / mpg_uk
    except Exception:
        return None

def ev_parity_rate_p_per_kwh(p_per_litre: float, mpg_uk: float, eff_mi_per_kwh: float) -> Optional[float]:
    """
    EV parity rate (p/kWh) = petrol p/mi / eff mi/kWh
    Where petrol p/mi is from petrol_ppm().
    Returns pence per kWh for direct comparison with tariffs.
    """
    ppm = petrol_ppm(p_per_litre, mpg_uk)
    try:
        if ppm is None or eff_mi_per_kwh <= 0:
            return None
        return ppm / eff_mi_per_kwh
    except Exception:
        return None

def ev_parity_rate_gbp_per_kwh(p_per_litre: float, mpg_uk: float, eff_mi_per_kwh: float) -> Optional[float]:
    """
    EV parity rate (GBP/kWh) - legacy function for backward compatibility.
    Use ev_parity_rate_p_per_kwh for new code.
    """
    parity_p = ev_parity_rate_p_per_kwh(p_per_litre, mpg_uk, eff_mi_per_kwh)
    try:
        if parity_p is None:
            return None
        return parity_p / 100.0
    except Exception:
        return None

def format_petrol_ppm(ppm: Optional[float]) -> str:
    """Format petrol pence per mile with appropriate precision."""
    if ppm is None:
        return "—"
    if ppm < 10:
        return f"{ppm:.2f} p/mi"
    else:
        return f"{ppm:.1f} p/mi"

def format_ev_parity_rate(rate_p_per_kwh: Optional[float]) -> str:
    """Format EV parity rate consistently (1 decimal place in p/kWh)."""
    from services.formatting import fmt_p_per_kwh
    return fmt_p_per_kwh(rate_p_per_kwh)

def format_ev_parity_rate_legacy(rate_gbp_per_kwh: Optional[float]) -> str:
    """Format EV parity rate in legacy £/kWh format (deprecated)."""
    if rate_gbp_per_kwh is None:
        return "—"
    return f"£{rate_gbp_per_kwh:.3f}/kWh"

def get_parity_comparison(session_effective_p_per_kwh: float, parity_rate_p_per_kwh: Optional[float]) -> dict:
    """
    Compare session effective rate vs parity rate.
    Both rates should be in p/kWh for direct comparison.
    Returns dict with comparison result and tooltip info.
    """
    if parity_rate_p_per_kwh is None:
        return {
            'status': 'unknown',
            'label': '—',
            'tooltip': 'Parity rate unavailable'
        }
    
    is_cheaper = session_effective_p_per_kwh < parity_rate_p_per_kwh
    
    return {
        'status': 'cheaper' if is_cheaper else 'dearer',
        'label': '✓ cheaper' if is_cheaper else '✗ dearer',
        'tooltip': f"EV parity {format_ev_parity_rate(parity_rate_p_per_kwh)}. This session effective rate {session_effective_p_per_kwh:.1f} p/kWh."
    }
