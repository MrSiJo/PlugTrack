#!/usr/bin/env python3
"""
Insights Service for PlugTrack Phase 5.1

Provides higher-signal insights without new APIs:
- £/10% SOC calculations
- Home ROI delta comparisons  
- Loss estimates
- Battery hygiene metrics
- Location leaderboards
"""

from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy import func, and_, desc, asc
from datetime import datetime, timedelta

from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from services.derived_metrics import DerivedMetricsService
from services.cost_parity import get_parity_comparison, ev_parity_rate_p_per_kwh


class InsightsService:
    """Service for Phase 5.1 enhanced insights"""
    
    @staticmethod
    def calculate_cost_per_10_percent_soc(session, total_cost: float) -> Optional[float]:
        """
        Calculate £/10% SOC metric.
        Formula: total_cost / ((ΔSOC)/10)
        Guards for ΔSOC=0
        """
        if not session:
            return None
            
        delta_soc = session.soc_to - session.soc_from
        if delta_soc <= 0:
            return None
            
        # Convert to £/10% SOC
        cost_per_10_percent = total_cost / (delta_soc / 10.0)
        return cost_per_10_percent
    
    @staticmethod
    def calculate_home_roi_delta(session, metrics: Dict, user_id: int) -> Optional[float]:
        """
        Calculate Home ROI delta (p/mi) vs 30-day home baseline.
        Excludes free sessions from baseline calculation.
        Returns delta in pence per mile.
        """
        if not session or not metrics.get('cost_per_mile'):
            return None
            
        # Skip if this is a free session
        if session.cost_per_kwh <= 0:
            return None
            
        # Get 30-day home baseline (exclude free sessions)
        thirty_days_ago = datetime.now().date() - timedelta(days=30)
        
        home_sessions = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.date >= thirty_days_ago,
                ChargingSession.cost_per_kwh > 0,  # Exclude free sessions
                # Use home detection logic
                func.lower(ChargingSession.location_label).contains('home') |
                func.lower(ChargingSession.location_label).contains('garage') |
                func.lower(ChargingSession.location_label).contains('driveway')
            )
        ).all()
        
        if not home_sessions:
            return None
            
        # Calculate home baseline cost per mile
        total_home_cost = 0
        total_home_miles = 0
        
        for home_session in home_sessions:
            session_cost = home_session.charge_delivered_kwh * home_session.cost_per_kwh
            # Use derived metrics to get consistent miles calculation
            car = Car.query.get(home_session.car_id)
            if car:
                session_metrics = DerivedMetricsService.calculate_session_metrics(home_session, car)
                if session_metrics['miles_gained'] > 0:
                    total_home_cost += session_cost
                    total_home_miles += session_metrics['miles_gained']
        
        if total_home_miles <= 0:
            return None
            
        home_baseline_cost_per_mile = total_home_cost / total_home_miles
        
        # Calculate delta in pence per mile
        current_cost_per_mile = metrics['cost_per_mile']
        delta_pence_per_mile = (current_cost_per_mile - home_baseline_cost_per_mile) * 100
        
        return delta_pence_per_mile
    
    @staticmethod  
    def calculate_loss_estimate(session, car: Car) -> Optional[float]:
        """
        Calculate loss estimate (%) in Details.
        Formula: expected_soc_from_kwh – observed ΔSOC
        Uses car battery_kwh for expected calculation.
        """
        if not session or not car or not car.battery_kwh:
            return None
            
        delta_soc_observed = session.soc_to - session.soc_from
        
        # Calculate expected SOC change based on kWh delivered
        # Assume 100% SOC = battery_kwh capacity
        expected_soc_change = (session.charge_delivered_kwh / car.battery_kwh) * 100
        
        # Loss estimate: expected - observed (positive = loss, negative = better than expected)
        loss_percent = expected_soc_change - delta_soc_observed
        
        return loss_percent
    
    @staticmethod
    def get_battery_hygiene_metrics(user_id: int, car_id: Optional[int] = None, days: int = 30) -> Dict[str, Any]:
        """
        Get battery hygiene widget data for Dashboard.
        Returns time distribution in SoC bands and 100% charge info.
        """
        # Build base query for the specified period
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        query = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.date >= start_date,
                ChargingSession.date <= end_date
            )
        )
        
        if car_id:
            query = query.filter(ChargingSession.car_id == car_id)
            
        sessions = query.all()
        
        if not sessions:
            return {
                'soc_bands': {'low': 0, 'normal': 0, 'high': 0},
                'last_100_date': None,
                'days_since_100': None,
                'recommended_frequency': None,
                'due_by_date': None,
                'is_overdue': False,
                'total_sessions': 0
            }
        
        # Count sessions in SoC bands based on soc_to (ending SoC)
        soc_bands = {'low': 0, 'normal': 0, 'high': 0}  # <30%, 30-80%, >80%
        
        for session in sessions:
            if session.soc_to < 30:
                soc_bands['low'] += 1
            elif session.soc_to <= 80:
                soc_bands['normal'] += 1
            else:
                soc_bands['high'] += 1
        
        # Find last 100% charge
        full_charge_query = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.soc_to >= 100
            )
        )
        
        if car_id:
            full_charge_query = full_charge_query.filter(ChargingSession.car_id == car_id)
            
        last_100_session = full_charge_query.order_by(desc(ChargingSession.date)).first()
        
        last_100_date = last_100_session.date if last_100_session else None
        days_since_100 = (end_date - last_100_date).days if last_100_date else None
        
        # Get car's recommended frequency for due date calculation
        car = None
        if car_id:
            car = Car.query.get(car_id)
        elif sessions:
            # Use the car from the most recent session if no specific car_id
            car = Car.query.get(sessions[0].car_id)
            
        recommended_frequency = None
        due_by_date = None
        is_overdue = False
        
        if car and car.recommended_full_charge_enabled and car.recommended_full_charge_frequency_value:
            if car.recommended_full_charge_frequency_unit == 'days':
                recommended_frequency = car.recommended_full_charge_frequency_value
            elif car.recommended_full_charge_frequency_unit == 'weeks':
                recommended_frequency = car.recommended_full_charge_frequency_value * 7
            elif car.recommended_full_charge_frequency_unit == 'months':
                recommended_frequency = car.recommended_full_charge_frequency_value * 30
                
            if recommended_frequency and last_100_date:
                due_by_date = last_100_date + timedelta(days=recommended_frequency)
                is_overdue = end_date > due_by_date
        
        return {
            'soc_bands': soc_bands,
            'last_100_date': last_100_date,
            'days_since_100': days_since_100,
            'recommended_frequency': recommended_frequency,
            'due_by_date': due_by_date,
            'is_overdue': is_overdue,
            'total_sessions': len(sessions),
            'period_days': days
        }
    
    @staticmethod
    def get_location_leaderboard(user_id: int, car_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get location leaderboard with median £/kWh, £/mi, typical SoC ranges, and session counts.
        """
        # Build base query
        query = ChargingSession.query.filter(ChargingSession.user_id == user_id)
        
        if car_id:
            query = query.filter(ChargingSession.car_id == car_id)
            
        sessions = query.all()
        
        if not sessions:
            return []
        
        # Group sessions by location
        location_groups = {}
        
        for session in sessions:
            location = session.location_label or 'Unknown'
            
            if location not in location_groups:
                location_groups[location] = {
                    'sessions': [],
                    'location': location
                }
                
            location_groups[location]['sessions'].append(session)
        
        # Calculate metrics for each location
        location_stats = []
        
        for location, data in location_groups.items():
            sessions_list = data['sessions']
            
            if len(sessions_list) < 2:  # Skip locations with too few sessions
                continue
                
            # Calculate metrics using derived metrics service
            cost_per_kwh_values = []
            cost_per_mile_values = []
            soc_from_values = []
            soc_to_values = []
            total_sessions = len(sessions_list)
            
            for session in sessions_list:
                # Cost per kWh is direct
                if session.cost_per_kwh > 0:  # Exclude free sessions
                    cost_per_kwh_values.append(session.cost_per_kwh)
                
                # Get cost per mile from derived metrics
                car = Car.query.get(session.car_id)
                if car:
                    metrics = DerivedMetricsService.calculate_session_metrics(session, car)
                    if metrics['cost_per_mile'] > 0:
                        cost_per_mile_values.append(metrics['cost_per_mile'])
                
                # SoC values
                if session.soc_from is not None:
                    soc_from_values.append(session.soc_from)
                if session.soc_to is not None:
                    soc_to_values.append(session.soc_to)
            
            # Calculate medians and typical values
            median_cost_per_kwh = InsightsService._calculate_median(cost_per_kwh_values) if cost_per_kwh_values else 0
            median_cost_per_mile = InsightsService._calculate_median(cost_per_mile_values) if cost_per_mile_values else 0
            typical_soc_from = InsightsService._calculate_median(soc_from_values) if soc_from_values else 0
            typical_soc_to = InsightsService._calculate_median(soc_to_values) if soc_to_values else 0
            
            location_stats.append({
                'location': location,
                'session_count': total_sessions,
                'median_cost_per_kwh': median_cost_per_kwh,
                'median_cost_per_mile': median_cost_per_mile,
                'typical_soc_from': typical_soc_from,
                'typical_soc_to': typical_soc_to,
                'typical_soc_range': f"{int(typical_soc_from)}% → {int(typical_soc_to)}%" if typical_soc_from and typical_soc_to else "N/A"
            })
        
        # Sort by session count (most used locations first), then by cost efficiency
        location_stats.sort(key=lambda x: (-x['session_count'], x['median_cost_per_kwh']))
        
        return location_stats[:limit]
    
    @staticmethod
    def _calculate_median(values: List[float]) -> float:
        """Calculate median of a list of values"""
        if not values:
            return 0
            
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        if n % 2 == 0:
            return (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2
        else:
            return sorted_values[n//2]
    
    @staticmethod
    def generate_summary(session_id: int) -> Optional[str]:
        """
        Generate a template-based, non-AI summary for a charging session.
        Includes variants: home vs public, p/mi vs petrol parity, DC taper flag.
        Returns a human-readable summary string.
        """
        session = ChargingSession.query.get(session_id)
        if not session:
            return None
        
        car = Car.query.get(session.car_id)
        if not car:
            return None
        
        # Get derived metrics
        metrics = DerivedMetricsService.calculate_session_metrics(session, car)
        
        # Determine session characteristics
        is_home = InsightsService._is_home_session(session)
        is_free = session.cost_per_kwh <= 0
        is_dc = session.charge_type.upper() == 'DC'
        delta_soc = session.soc_to - session.soc_from
        session_size = DerivedMetricsService.classify_session_size(delta_soc)
        
        # Build summary components
        summary_parts = []
        
        # 1. Session type and location
        if is_home:
            summary_parts.append(f"Home {session_size} charge")
        else:
            location = session.location_label or "Unknown location"
            summary_parts.append(f"Public {session_size} charge at {location}")
        
        # 2. Energy and efficiency
        energy_str = f"{session.charge_delivered_kwh:.1f} kWh"
        if metrics.get('efficiency_used'):
            efficiency_str = f"{metrics['efficiency_used']:.1f} mi/kWh"
            summary_parts.append(f"delivered {energy_str} with {efficiency_str} efficiency")
        else:
            summary_parts.append(f"delivered {energy_str}")
        
        # 3. Cost information
        if is_free:
            summary_parts.append("at no cost")
        else:
            cost_str = f"{session.cost_per_kwh:.2f} £/kWh"
            if metrics.get('cost_per_mile'):
                cost_per_mile_pence = metrics['cost_per_mile'] * 100
                summary_parts.append(f"at {cost_str} ({cost_per_mile_pence:.1f}p/mi)")
            else:
                summary_parts.append(f"at {cost_str}")
            
            # Add petrol parity comparison if available
            parity_comparison = InsightsService._get_petrol_parity_summary(session, car, metrics)
            if parity_comparison:
                summary_parts.append(parity_comparison)
        
        # 4. DC taper information
        if is_dc and session.charge_speed_kw:
            avg_power = metrics.get('avg_power_kw', session.charge_speed_kw)
            if avg_power < session.charge_speed_kw * 0.8:  # Significant taper detected
                summary_parts.append(f"with DC taper (avg {avg_power:.0f} kW)")
        
        # 5. Duration and SoC range
        duration_hours = session.duration_mins / 60
        if duration_hours >= 1:
            summary_parts.append(f"over {duration_hours:.1f} hours ({session.soc_from}% → {session.soc_to}%)")
        else:
            summary_parts.append(f"in {session.duration_mins} mins ({session.soc_from}% → {session.soc_to}%)")
        
        # Combine all parts into a readable sentence
        if len(summary_parts) >= 2:
            # Join most parts with commas, last part with "and"
            main_parts = summary_parts[:-1]
            last_part = summary_parts[-1]
            summary = ", ".join(main_parts) + f", {last_part}."
        else:
            summary = ". ".join(summary_parts) + "."
        
        # Capitalize first letter
        summary = summary[0].upper() + summary[1:] if summary else summary
        
        return summary
    
    @staticmethod
    def _is_home_session(session: ChargingSession) -> bool:
        """Determine if session is a home charging session"""
        # Use same logic as DerivedMetricsService._is_home_like
        try:
            if hasattr(session, "is_home_charging") and session.is_home_charging is not None:
                return bool(session.is_home_charging)
        except Exception:
            pass
        label = (session.location_label or "").lower()
        return any(keyword in label for keyword in ("home", "garage", "driveway"))
    
    @staticmethod
    def _get_petrol_parity_summary(session: ChargingSession, car: Car, metrics: Dict) -> Optional[str]:
        """Get petrol parity comparison summary snippet"""
        if not metrics.get('efficiency_used') or not session.cost_per_kwh:
            return None
        
        # Get user settings for petrol price and MPG
        petrol_ppl = Settings.get_setting(session.user_id, 'petrol_ppl')
        mpg_uk = Settings.get_setting(session.user_id, 'mpg_uk')
        
        if not petrol_ppl or not mpg_uk:
            return None
        
        try:
            petrol_ppl = float(petrol_ppl)
            mpg_uk = float(mpg_uk)
        except (ValueError, TypeError):
            return None
        
        # Calculate EV parity rate
        parity_rate_p_per_kwh = ev_parity_rate_p_per_kwh(
            petrol_ppl, 
            mpg_uk, 
            metrics['efficiency_used']
        )
        
        if parity_rate_p_per_kwh is None:
            return None
        
        # Session effective rate in p/kWh
        session_rate_p_per_kwh = session.cost_per_kwh * 100
        
        # Get comparison
        comparison = get_parity_comparison(session_rate_p_per_kwh, parity_rate_p_per_kwh)
        
        if comparison['status'] == 'cheaper':
            savings_percent = ((parity_rate_p_per_kwh - session_rate_p_per_kwh) / parity_rate_p_per_kwh) * 100
            return f"saving {savings_percent:.0f}% vs petrol"
        elif comparison['status'] == 'dearer':
            extra_percent = ((session_rate_p_per_kwh - parity_rate_p_per_kwh) / parity_rate_p_per_kwh) * 100
            return f"costing {extra_percent:.0f}% more than petrol"
        
        return None
