# services/formatting.py
"""
Centralized formatting functions for consistent display across PlugTrack.
"""

def fmt_p_per_kwh(pence_per_kwh: float = None) -> str:
    """
    Format pence per kWh with consistent precision (1 decimal place).
    
    Args:
        pence_per_kwh: Value in pence per kWh, or None for invalid/missing
        
    Returns:
        Formatted string like "2.3 p/kWh" or "—" if None
    """
    if pence_per_kwh is None:
        return "—"
    return f"{pence_per_kwh:.1f} p/kWh"

def fmt_p_per_litre(pence_per_litre: float = None) -> str:
    """Format pence per litre."""
    if pence_per_litre is None:
        return "—"
    return f"{pence_per_litre:.1f} p/L"

def fmt_p_per_mile(pence_per_mile: float = None) -> str:
    """Format pence per mile with appropriate precision."""
    if pence_per_mile is None:
        return "—"
    if pence_per_mile < 10:
        return f"{pence_per_mile:.2f} p/mi"
    else:
        return f"{pence_per_mile:.1f} p/mi"

def fmt_mpg(mpg: float = None) -> str:
    """Format miles per gallon."""
    if mpg is None:
        return "—"
    return f"{mpg:.1f} MPG"

def fmt_efficiency(mi_per_kwh: float = None) -> str:
    """Format efficiency in mi/kWh."""
    if mi_per_kwh is None:
        return "—"
    return f"{mi_per_kwh:.1f} mi/kWh"

def fmt_temperature(temp_c: float = None) -> str:
    """Format temperature in Celsius."""
    if temp_c is None:
        return "—"
    return f"{temp_c:.1f}°C"
