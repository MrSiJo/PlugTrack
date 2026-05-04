"""
Analytics Aggregation Service for PlugTrack Phase 6
Provides lightweight JSON summaries for dashboards and API endpoints.
"""

from typing import Dict, Optional, List, Tuple
from sqlalchemy import func, desc, asc, and_, or_
from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from services.derived_metrics import DerivedMetricsService
from services.cost_parity import petrol_ppm
from datetime import datetime, timedelta


class AnalyticsAggService:
    """Service for aggregated analytics calculations"""
    
    @staticmethod
    def get_analytics_summary(user_id: int, car_id: Optional[int] = None) -> Dict:
        """
        Get aggregated analytics summary for /api/analytics/summary endpoint.
        Returns weighted efficiency, lifetime totals, and cheapest/most expensive sessions.
        """
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get total sessions count
        total_sessions = query.count()
        
        if total_sessions == 0:
            return {
                "weighted_efficiency": 0,
                "lifetime": {"kwh": 0, "miles": 0, "cost": 0, "saved_vs_petrol": 0},
                "most_expensive": None,
                "cheapest": None
            }
        
        # Calculate kWh-weighted efficiency
        weighted_efficiency = AnalyticsAggService._calculate_weighted_efficiency(user_id, car_id)
        
        # Calculate lifetime totals
        lifetime_totals = AnalyticsAggService._calculate_lifetime_totals(user_id, car_id, weighted_efficiency)
        
        # Find cheapest and most expensive sessions by pence per mile
        cheapest_session, most_expensive_session = AnalyticsAggService._find_cost_extremes(user_id, car_id)
        
        return {
            "weighted_efficiency": round(weighted_efficiency, 2) if weighted_efficiency else 0,
            "lifetime": lifetime_totals,
            "most_expensive": most_expensive_session,
            "cheapest": cheapest_session
        }
    
    @staticmethod
    def _calculate_weighted_efficiency(user_id: int, car_id: Optional[int] = None) -> Optional[float]:
        """Calculate kWh-weighted efficiency from sessions with observed efficiency data"""
        query = ChargingSession.query.filter(
            ChargingSession.user_id == user_id,
            ChargingSession.odometer.isnot(None),
            ChargingSession.is_baseline == False
        )
        
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.all()
        
        if not sessions:
            return None
        
        total_weighted_numerator = 0
        total_weighted_denominator = 0
        
        for session in sessions:
            # Get observed efficiency for this session
            metrics = DerivedMetricsService.calculate_session_metrics(session, None)
            if metrics['efficiency_used'] is not None and metrics['efficiency_used'] > 0 and not metrics['low_confidence']:
                total_weighted_numerator += metrics['efficiency_used'] * session.charge_delivered_kwh
                total_weighted_denominator += session.charge_delivered_kwh
        
        if total_weighted_denominator > 0:
            return total_weighted_numerator / total_weighted_denominator
        
        # Fallback to dynamic efficiency if no observed session data
        return DerivedMetricsService.calculate_dynamic_efficiency(user_id, car_id)
    
    @staticmethod
    def _calculate_lifetime_totals(user_id: int, car_id: Optional[int] = None, efficiency: Optional[float] = None) -> Dict:
        """Calculate lifetime totals for kWh, miles, cost, and petrol savings"""
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get energy and cost totals
        totals = query.with_entities(
            func.sum(ChargingSession.charge_delivered_kwh).label('total_kwh'),
            func.sum(ChargingSession.charge_delivered_kwh * ChargingSession.cost_per_kwh).label('total_cost')
        ).first()
        
        total_kwh = float(totals.total_kwh or 0)
        total_cost = float(totals.total_cost or 0)
        
        # Calculate miles using efficiency
        total_miles = 0
        if efficiency and total_kwh > 0:
            total_miles = total_kwh * efficiency
        
        # Calculate petrol savings
        saved_vs_petrol = AnalyticsAggService._calculate_petrol_savings(user_id, total_miles, total_cost)
        
        return {
            "kwh": round(total_kwh, 1),
            "miles": round(total_miles, 1),
            "cost": round(total_cost, 2),
            "saved_vs_petrol": round(saved_vs_petrol, 2)
        }
    
    @staticmethod
    def _calculate_petrol_savings(user_id: int, total_miles: float, total_ev_cost: float) -> float:
        """Calculate how much was saved vs equivalent petrol cost"""
        if total_miles <= 0:
            return 0
        
        # Get petrol settings
        petrol_price = Settings.get_setting(user_id, 'petrol_price_p_per_litre', 128.9)
        petrol_mpg = Settings.get_setting(user_id, 'petrol_mpg', 60.0)
        
        try:
            petrol_price = float(petrol_price)
            petrol_mpg = float(petrol_mpg)
            
            # Calculate petrol cost per mile in pence
            petrol_cost_per_mile = petrol_ppm(petrol_price, petrol_mpg)
            if petrol_cost_per_mile:
                # Total petrol cost for same miles in pounds
                total_petrol_cost = (petrol_cost_per_mile * total_miles) / 100
                # Savings = what petrol would have cost - what EV actually cost
                return max(0, total_petrol_cost - total_ev_cost)
        except (ValueError, TypeError):
            pass
        
        return 0
    
    @staticmethod
    def _find_cost_extremes(user_id: int, car_id: Optional[int] = None) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Find cheapest and most expensive sessions by cost per mile"""
        query = ChargingSession.query.filter(
            ChargingSession.user_id == user_id,
            ChargingSession.cost_per_kwh > 0  # Only paid sessions
        )
        
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.all()
        
        if not sessions:
            return None, None
        
        # Calculate cost per mile for each session
        session_costs = []
        for session in sessions:
            metrics = DerivedMetricsService.calculate_session_metrics(session, None)
            if metrics['cost_per_mile'] > 0 and metrics['efficiency_used'] is not None and metrics['efficiency_used'] > 0:
                cost_per_mile_pence = metrics['cost_per_mile'] * 100  # Convert to pence
                session_costs.append({
                    'session': session,
                    'cost_per_mile': cost_per_mile_pence,
                    'efficiency': metrics['efficiency_used']
                })
        
        if not session_costs:
            return None, None
        
        # Sort by cost per mile
        session_costs.sort(key=lambda x: x['cost_per_mile'])
        
        cheapest = session_costs[0]
        most_expensive = session_costs[-1]
        
        def format_session_summary(session_data):
            session = session_data['session']
            return {
                "session_id": session.id,
                "cost_per_mile": round(session_data['cost_per_mile'], 1),
                "date": session.date.strftime('%B %d, %Y'),
                "location": session.location_label,
                "kwh": session.charge_delivered_kwh,
                "cost_per_kwh": session.cost_per_kwh
            }
        
        return format_session_summary(cheapest), format_session_summary(most_expensive)
    
    @staticmethod
    def get_seasonal_analytics(user_id: int, car_id: Optional[int] = None) -> Dict:
        """
        Get seasonal analytics for /api/analytics/seasonal endpoint.
        Returns efficiency vs ambient temperature bins.
        """
        query = ChargingSession.query.filter(
            ChargingSession.user_id == user_id,
            ChargingSession.ambient_temp_c.isnot(None),
            ChargingSession.odometer.isnot(None),
            ChargingSession.is_baseline == False
        )
        
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.all()
        
        if not sessions:
            return {"temperature_bins": []}
        
        # Define temperature bins (0-5°C, 5-10°C, etc.)
        bins = []
        for start_temp in range(-10, 35, 5):  # -10°C to 35°C in 5°C increments
            end_temp = start_temp + 5
            bins.append({
                "range": f"{start_temp}°C to {end_temp}°C",
                "start_temp": start_temp,
                "end_temp": end_temp,
                "sessions": [],
                "avg_efficiency": 0,
                "session_count": 0
            })
        
        # Categorize sessions into temperature bins
        for session in sessions:
            temp = session.ambient_temp_c
            metrics = DerivedMetricsService.calculate_session_metrics(session, None)
            
            if metrics['efficiency_used'] and not metrics['low_confidence']:
                # Find appropriate bin
                for bin_data in bins:
                    if bin_data['start_temp'] <= temp < bin_data['end_temp']:
                        bin_data['sessions'].append({
                            'efficiency': metrics['efficiency_used'],
                            'kwh': session.charge_delivered_kwh
                        })
                        break
        
        # Calculate kWh-weighted average efficiency for each bin
        result_bins = []
        for bin_data in bins:
            if bin_data['sessions']:
                # Calculate kWh-weighted efficiency
                total_weighted = sum(s['efficiency'] * s['kwh'] for s in bin_data['sessions'])
                total_kwh = sum(s['kwh'] for s in bin_data['sessions'])
                
                if total_kwh > 0:
                    avg_efficiency = total_weighted / total_kwh
                    result_bins.append({
                        "range": bin_data['range'],
                        "avg_efficiency": round(avg_efficiency, 2),
                        "session_count": len(bin_data['sessions'])
                    })
        
        return {"temperature_bins": result_bins}
    
    @staticmethod
    def get_leaderboard_analytics(user_id: int, car_id: Optional[int] = None) -> Dict:
        """
        Get leaderboard analytics for /api/analytics/leaderboard endpoint.
        Returns per-location metrics (median p/mi, p/kWh, session counts).
        """
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.all()
        
        if not sessions:
            return {"locations": []}
        
        # Group sessions by location
        location_data = {}
        
        for session in sessions:
            location = session.location_label or "Unknown Location"
            
            if location not in location_data:
                location_data[location] = {
                    'sessions': [],
                    'costs_per_kwh': [],
                    'costs_per_mile': []
                }
            
            location_data[location]['sessions'].append(session)
            
            # Collect cost per kWh (only for paid sessions)
            if session.cost_per_kwh > 0:
                location_data[location]['costs_per_kwh'].append(session.cost_per_kwh)
            
            # Calculate cost per mile for this session
            metrics = DerivedMetricsService.calculate_session_metrics(session, None)
            if metrics['cost_per_mile'] > 0:
                location_data[location]['costs_per_mile'].append(metrics['cost_per_mile'] * 100)  # Convert to pence
        
        # Calculate statistics for each location
        locations = []
        for location, data in location_data.items():
            session_count = len(data['sessions'])
            
            # Calculate medians
            median_p_per_kwh = 0
            if data['costs_per_kwh']:
                costs_sorted = sorted(data['costs_per_kwh'])
                n = len(costs_sorted)
                median_p_per_kwh = costs_sorted[n // 2] if n % 2 == 1 else (costs_sorted[n // 2 - 1] + costs_sorted[n // 2]) / 2
                median_p_per_kwh *= 100  # Convert to pence
            
            median_p_per_mile = 0
            if data['costs_per_mile']:
                costs_sorted = sorted(data['costs_per_mile'])
                n = len(costs_sorted)
                median_p_per_mile = costs_sorted[n // 2] if n % 2 == 1 else (costs_sorted[n // 2 - 1] + costs_sorted[n // 2]) / 2
            
            locations.append({
                "location": location,
                "session_count": session_count,
                "median_p_per_kwh": round(median_p_per_kwh, 1),
                "median_p_per_mile": round(median_p_per_mile, 1)
            })
        
        # Sort by session count (most used locations first)
        locations.sort(key=lambda x: x['session_count'], reverse=True)
        
        return {"locations": locations}
    
    @staticmethod
    def get_sweetspot_analytics(user_id: int, car_id: Optional[int] = None) -> Dict:
        """
        Get SoC sweet spot analytics for /api/analytics/sweetspot endpoint.
        Returns SoC window efficiencies (e.g., 20-60% most efficient).
        """
        query = ChargingSession.query.filter(
            ChargingSession.user_id == user_id,
            ChargingSession.odometer.isnot(None),
            ChargingSession.is_baseline == False
        )
        
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.all()
        
        if not sessions:
            return {"soc_windows": []}
        
        # Define SoC windows
        windows = [
            {"range": "0-20%", "start": 0, "end": 20},
            {"range": "20-40%", "start": 20, "end": 40},
            {"range": "40-60%", "start": 40, "end": 60},
            {"range": "60-80%", "start": 60, "end": 80},
            {"range": "80-100%", "start": 80, "end": 100}
        ]
        
        # Categorize sessions by SoC window
        for window in windows:
            window['sessions'] = []
            window['efficiencies'] = []
        
        for session in sessions:
            soc_start = session.soc_from
            
            # Find appropriate window for this session's starting SoC
            for window in windows:
                if window['start'] <= soc_start < window['end']:
                    metrics = DerivedMetricsService.calculate_session_metrics(session, None)
                    if metrics['efficiency_used'] and not metrics['low_confidence']:
                        window['sessions'].append(session)
                        window['efficiencies'].append({
                            'efficiency': metrics['efficiency_used'],
                            'kwh': session.charge_delivered_kwh
                        })
                    break
        
        # Calculate kWh-weighted efficiency for each window
        result_windows = []
        for window in windows:
            if window['efficiencies']:
                # Calculate kWh-weighted efficiency
                total_weighted = sum(e['efficiency'] * e['kwh'] for e in window['efficiencies'])
                total_kwh = sum(e['kwh'] for e in window['efficiencies'])
                
                if total_kwh > 0:
                    avg_efficiency = total_weighted / total_kwh
                    result_windows.append({
                        "soc_range": window['range'],
                        "avg_efficiency": round(avg_efficiency, 2),
                        "session_count": len(window['sessions'])
                    })
        
        # Sort by efficiency (best to worst)
        result_windows.sort(key=lambda x: x['avg_efficiency'], reverse=True)
        
        return {"soc_windows": result_windows}
