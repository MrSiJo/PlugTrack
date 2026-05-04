from models.settings import Settings

class BlendedChargeService:
    """Service for calculating blended charging strategies (DC + Home)"""
    
    # Default DC taper bands (percent → power ratio)
    DEFAULT_TAPER_BANDS = {
        (10, 50): 1.00,   # 10-50%: full power
        (50, 70): 0.70,   # 50-70%: 70% power
        (70, 80): 0.45    # 70-80%: 45% power
    }
    
    @staticmethod
    def calculate_blended_charge(
        start_soc, 
        dc_stop_soc, 
        home_target_soc, 
        dc_power_kw, 
        dc_cost_per_kwh, 
        home_cost_per_kwh, 
        car_battery_kwh,
        home_power_kw=7.4,  # Default home charger power (will be overridden by user setting)
        taper_bands=None
    ):
        """Calculate a blended charging strategy (DC + Home)"""
        
        if taper_bands is None:
            taper_bands = BlendedChargeService.DEFAULT_TAPER_BANDS
        
        # Validate inputs
        if not (0 <= start_soc < dc_stop_soc < home_target_soc <= 100):
            raise ValueError("Invalid SoC values: start < dc_stop < home_target")
        
        if dc_power_kw <= 0 or car_battery_kwh <= 0 or home_power_kw <= 0:
            raise ValueError("Invalid power or battery capacity")
        
        # Calculate DC charging phase
        dc_result = BlendedChargeService._calculate_dc_phase(
            start_soc, dc_stop_soc, dc_power_kw, car_battery_kwh, taper_bands
        )
        
        # Calculate home charging phase
        home_result = BlendedChargeService._calculate_home_phase(
            dc_stop_soc, home_target_soc, car_battery_kwh, home_power_kw
        )
        
        # Calculate costs
        dc_cost = dc_result['kwh'] * dc_cost_per_kwh
        home_cost = home_result['kwh'] * home_cost_per_kwh
        total_cost = dc_cost + home_cost
        
        # Calculate total miles gained
        total_kwh = dc_result['kwh'] + home_result['kwh']
        total_miles = total_kwh * 3.7  # Default efficiency, will be overridden by caller
        
        # Calculate blended cost per mile
        cost_per_mile = total_cost / total_miles if total_miles > 0 else 0
        
        return {
            'dc': {
                'kwh': dc_result['kwh'],
                'time_hours': dc_result['time_hours'],
                'cost': dc_cost,
                'soc_range': f"{start_soc}% → {dc_stop_soc}%"
            },
            'home': {
                'kwh': home_result['kwh'],
                'time_hours': home_result['time_hours'],
                'cost': home_cost,
                'soc_range': f"{dc_stop_soc}% → {home_target_soc}%"
            },
            'total': {
                'kwh': total_kwh,
                'time_hours': dc_result['time_hours'] + home_result['time_hours'],
                'cost': total_cost,
                'cost_per_mile': cost_per_mile,
                'soc_range': f"{start_soc}% → {home_target_soc}%"
            }
        }
    
    @staticmethod
    def _calculate_dc_phase(start_soc, stop_soc, power_kw, battery_kwh, taper_bands):
        """Calculate DC charging phase with taper model"""
        total_kwh = 0
        total_time = 0
        
        # Process each SoC band
        for (band_start, band_end), power_ratio in taper_bands.items():
            # Check if this band overlaps with our target range
            if band_end <= start_soc or band_start >= stop_soc:
                continue
            
            # Calculate the SoC range for this band
            band_soc_start = max(band_start, start_soc)
            band_soc_end = min(band_end, stop_soc)
            
            if band_soc_start >= band_soc_end:
                continue
            
            # Calculate energy and time for this band
            soc_change = band_soc_end - band_soc_start
            band_kwh = (soc_change / 100) * battery_kwh
            
            # Apply power taper
            effective_power = power_kw * power_ratio
            band_time = band_kwh / effective_power if effective_power > 0 else 0
            
            total_kwh += band_kwh
            total_time += band_time
        
        return {
            'kwh': total_kwh,
            'time_hours': total_time
        }
    
    @staticmethod
    def _calculate_home_phase(start_soc, target_soc, battery_kwh, home_power_kw):
        """Calculate home charging phase (assumed constant power)"""
        soc_change = target_soc - start_soc
        kwh = (soc_change / 100) * battery_kwh
        time_hours = kwh / home_power_kw if home_power_kw > 0 else 0
        
        return {
            'kwh': kwh,
            'time_hours': time_hours
        }
    
    @staticmethod
    def get_optimal_dc_stop(start_soc, home_rate, dc_rate, target_soc=80):
        """Calculate optimal DC stop point based on cost comparison"""
        # Simple heuristic: if DC is significantly more expensive, stop earlier
        if dc_rate > (home_rate * 1.5):
            # High cost DC - stop at 60%
            return min(60, start_soc + 30)
        elif dc_rate > (home_rate * 1.2):
            # Medium cost DC - stop at 65%
            return min(65, start_soc + 35)
        else:
            # Low cost DC - can go higher
            return min(70, start_soc + 40)
    
    @staticmethod
    def format_blend_summary(blend_result, efficiency_mpkwh):
        """Format blend result for display"""
        # Recalculate miles with actual efficiency
        total_miles = blend_result['total']['kwh'] * efficiency_mpkwh
        cost_per_mile = blend_result['total']['cost'] / total_miles if total_miles > 0 else 0
        
        return {
            'dc_summary': f"{blend_result['dc']['kwh']:.1f} kWh • {blend_result['dc']['time_hours']:.1f}h • £{blend_result['dc']['cost']:.2f}",
            'home_summary': f"{blend_result['home']['kwh']:.1f} kWh • {blend_result['home']['time_hours']:.1f}h • £{blend_result['home']['cost']:.2f}",
            'total_summary': f"£{blend_result['total']['cost']:.2f} • {cost_per_mile * 100:.1f} p/mi",
            'total_miles': total_miles,
            'cost_per_mile': cost_per_mile
        }
