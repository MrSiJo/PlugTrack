#!/usr/bin/env python3
"""
Utility functions for petrol cost calculations and comparisons.
"""

def calculate_petrol_threshold_p_per_kwh(petrol_price_p_per_litre, petrol_mpg, efficiency_mpkwh):
    """Calculate petrol cost threshold in p/kWh equivalent"""
    # Convert petrol price to cost per gallon
    # 1 UK gallon = 4.546 litres
    petrol_price_per_gallon = petrol_price_p_per_litre * 4.546
    
    # Calculate cost per mile
    cost_per_mile_p = petrol_price_per_gallon / petrol_mpg
    
    # Convert to p/kWh equivalent
    # If 1 kWh gives us efficiency_mpkwh miles, then:
    # cost_per_kwh = cost_per_mile * efficiency_mpkwh
    petrol_threshold_p_per_kwh = cost_per_mile_p * efficiency_mpkwh
    
    return round(petrol_threshold_p_per_kwh, 1)

def get_petrol_threshold_for_user(user_id, efficiency_mpkwh=None, settings_model=None):
    """Get petrol threshold for a specific user, optionally with custom efficiency"""
    if settings_model is None:
        # Import here to avoid circular imports
        from models.settings import Settings
        settings_model = Settings
    
    if efficiency_mpkwh is None:
        efficiency_mpkwh = float(settings_model.get_setting(user_id, 'default_efficiency_mpkwh', '3.7'))
    
    petrol_price_p_per_litre = float(settings_model.get_setting(user_id, 'petrol_price_p_per_litre', '128.9'))
    petrol_mpg = float(settings_model.get_setting(user_id, 'petrol_mpg', '60.0'))
    
    return calculate_petrol_threshold_p_per_kwh(petrol_price_p_per_litre, petrol_mpg, efficiency_mpkwh)
