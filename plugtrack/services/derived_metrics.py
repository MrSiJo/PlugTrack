from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from models.session_meta import SessionMeta
from sqlalchemy import func, and_, or_, not_, case
from datetime import datetime, timedelta
import pandas as pd

class DerivedMetricsService:
    """Service for calculating derived metrics from charging session data"""

    @staticmethod
    def calculate_session_metrics(session, car):
        """Calculate metrics for a single charging session"""
        # Get user settings for calculations
        petrol_threshold = float(Settings.get_setting(session.user_id, 'petrol_threshold_p_per_kwh', '52.5'))
        default_efficiency = float(Settings.get_setting(session.user_id, 'default_efficiency_mpkwh', '3.7'))
        
        # Total cost
        total_cost = session.charge_delivered_kwh * session.cost_per_kwh
        
        # Miles gained (estimated based on car efficiency)
        efficiency = car.efficiency_mpkwh if car and car.efficiency_mpkwh else default_efficiency
        miles_gained = session.charge_delivered_kwh * efficiency
        
        # Cost per mile
        cost_per_mile = 0
        if miles_gained > 0:
            cost_per_mile = total_cost / miles_gained
        
        # Battery added percentage
        battery_added_percent = session.soc_to - session.soc_from
        
        # Percentage per kWh (indicates effective usable capacity vs losses)
        percent_per_kwh = 0
        if session.charge_delivered_kwh > 0:
            percent_per_kwh = battery_added_percent / session.charge_delivered_kwh
        
        # Average power (when duration present)
        avg_power_kw = 0
        if session.duration_mins and session.duration_mins > 0:
            avg_power_kw = session.charge_delivered_kwh / (session.duration_mins / 60)
        
        # DC taper flag (heuristic)
        dc_taper_flag = False
        if session.charge_type == 'DC' and session.soc_to > 65:
            dc_taper_flag = True
        
        # Petrol threshold comparison
        threshold_ppm = petrol_threshold / efficiency if efficiency > 0 else 0
        is_cheaper_than_petrol = (cost_per_mile * 100) <= threshold_ppm if cost_per_mile > 0 else False
        
        # Home vs public charging
        is_home_charging = session.is_home_charging
        
        return {
            'total_cost': total_cost,
            'miles_gained': miles_gained,
            'cost_per_mile': cost_per_mile,
            'battery_added_percent': battery_added_percent,
            'percent_per_kwh': percent_per_kwh,
            'avg_power_kw': avg_power_kw,
            'dc_taper_flag': dc_taper_flag,
            'threshold_ppm': threshold_ppm,
            'is_cheaper_than_petrol': is_cheaper_than_petrol,
            'is_home_charging': is_home_charging,
            'efficiency_used': efficiency
        }

    @staticmethod
    def get_dashboard_metrics(user_id, date_from=None, date_to=None, car_id=None):
        """Get comprehensive dashboard metrics"""
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        
        # Apply filters
        if date_from:
            query = query.filter(ChargingSession.date >= date_from)
        if date_to:
            query = query.filter(ChargingSession.date <= date_to)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get basic counts and sums
        total_sessions = query.count()
        
        if total_sessions == 0:
            return {
                'total_sessions': 0,
                'total_kwh': 0,
                'total_cost': 0,
                'total_miles': 0,
                'avg_cost_per_kwh': 0,
                'avg_cost_per_mile': 0,
                'home_public_split': {'home': {'count': 0, 'percentage': 0}, 'public': {'count': 0, 'percentage': 0}},
                'ac_dc_split': {'AC': {'count': 0, 'percentage': 0}, 'DC': {'count': 0, 'percentage': 0}}
            }
        
        # Get energy and cost totals
        energy_cost = query.with_entities(
            func.sum(ChargingSession.charge_delivered_kwh).label('total_kwh'),
            func.sum(ChargingSession.charge_delivered_kwh * ChargingSession.cost_per_kwh).label('total_cost')
        ).first()
        
        total_kwh = energy_cost.total_kwh or 0
        total_cost = energy_cost.total_cost or 0
        
        # Calculate averages - handle free charging sessions properly
        # Get paid sessions only for average cost calculation
        paid_sessions_query = query.filter(ChargingSession.cost_per_kwh > 0)
        paid_kwh = paid_sessions_query.with_entities(
            func.sum(ChargingSession.charge_delivered_kwh)
        ).scalar() or 0
        
        avg_cost_per_kwh = total_cost / paid_kwh if paid_kwh > 0 else 0
        
        # Count free vs paid sessions
        free_sessions = query.filter(ChargingSession.cost_per_kwh == 0).count()
        paid_sessions = total_sessions - free_sessions
        
        # Get home vs public split
        home_sessions = query.filter(
            or_(
                ChargingSession.location_label.ilike('%home%'),
                ChargingSession.location_label.ilike('%garage%'),
                ChargingSession.location_label.ilike('%driveway%')
            )
        ).count()
        
        public_sessions = total_sessions - home_sessions
        
        # Calculate percentages for home vs public
        home_percentage = (home_sessions / total_sessions * 100) if total_sessions > 0 else 0
        public_percentage = (public_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        # Get AC vs DC split
        ac_sessions = query.filter_by(charge_type='AC').count()
        dc_sessions = query.filter_by(charge_type='DC').count()
        
        # Calculate percentages for AC vs DC
        ac_percentage = (ac_sessions / total_sessions * 100) if total_sessions > 0 else 0
        dc_percentage = (dc_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        # Calculate total miles and cost per mile (requires car efficiency data)
        total_miles = 0
        avg_cost_per_mile = 0
        
        # Get any available car for efficiency calculations if no specific car selected
        if not car_id:
            available_car = Car.query.filter_by(user_id=user_id).first()
            # Try dynamic efficiency first, fall back to car profile
            dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id)
            car_efficiency = available_car.efficiency_mpkwh if available_car else None
            final_efficiency = dynamic_efficiency or car_efficiency
            
            if final_efficiency:
                total_miles = total_kwh * final_efficiency
                avg_cost_per_mile = total_cost / total_miles if total_miles > 0 else 0
        else:
            car = Car.query.get(car_id)
            # Try dynamic efficiency first, fall back to car profile
            dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id, car_id)
            car_efficiency = car.efficiency_mpkwh if car else None
            final_efficiency = dynamic_efficiency or car_efficiency
            
            if final_efficiency:
                total_miles = total_kwh * final_efficiency
                avg_cost_per_mile = total_cost / total_miles if total_miles > 0 else 0
        
        return {
            'total_sessions': total_sessions,
            'total_kwh': total_kwh,
            'total_cost': total_cost,
            'total_miles': total_miles,
            'avg_cost_per_kwh': avg_cost_per_kwh,
            'avg_cost_per_mile': avg_cost_per_mile,
            'free_sessions': free_sessions,
            'paid_sessions': paid_sessions,
            'home_public_split': {
                'home': {'count': home_sessions, 'percentage': home_percentage},
                'public': {'count': public_sessions, 'percentage': public_percentage}
            },
            'ac_dc_split': {
                'AC': {'count': ac_sessions, 'percentage': ac_percentage},
                'DC': {'count': dc_sessions, 'percentage': dc_percentage}
            }
        }

    @staticmethod
    def get_chart_data(user_id, date_from=None, date_to=None, car_id=None):
        """Get data formatted for charts"""
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        
        # Apply filters
        if date_from:
            query = query.filter(ChargingSession.date >= date_from)
        if date_to:
            query = query.filter(ChargingSession.date <= date_to)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get daily aggregated data
        daily_data = query.with_entities(
            ChargingSession.date,
            func.sum(ChargingSession.charge_delivered_kwh).label('total_kwh'),
            func.avg(ChargingSession.charge_delivered_kwh / ChargingSession.duration_mins * 60).label('avg_power_kw')
        ).group_by(ChargingSession.date).order_by(ChargingSession.date).all()
        
        # Get daily cost data (only from paid sessions)
        daily_cost_data = query.filter(ChargingSession.cost_per_kwh > 0).with_entities(
            ChargingSession.date,
            func.avg(ChargingSession.cost_per_kwh).label('avg_cost_per_kwh'),
            func.sum(ChargingSession.charge_delivered_kwh * ChargingSession.cost_per_kwh).label('daily_cost')
        ).group_by(ChargingSession.date).order_by(ChargingSession.date).all()
        
        # Create a lookup for daily costs
        cost_lookup = {str(d.date): {'avg_cost': d.avg_cost_per_kwh, 'daily_cost': d.daily_cost} for d in daily_cost_data}
        
        # Get AC/DC split data
        ac_dc_data = query.with_entities(
            ChargingSession.date,
            func.sum(
                case(
                    (ChargingSession.charge_type == 'AC', ChargingSession.charge_delivered_kwh),
                    else_=0
                )
            ).label('ac_kwh'),
            func.sum(
                case(
                    (ChargingSession.charge_type == 'DC', ChargingSession.charge_delivered_kwh),
                    else_=0
                )
            ).label('dc_kwh')
        ).group_by(ChargingSession.date).order_by(ChargingSession.date).all()
        
        # Format for Chart.js
        dates = [str(d.date) for d in daily_data]
        cost_per_kwh = []
        energy_delivered = [float(d.total_kwh) for d in daily_data]
        
        # Handle cost per kWh - use 0 for days with only free charging
        for d in daily_data:
            date_str = str(d.date)
            if date_str in cost_lookup:
                cost_per_kwh.append(float(cost_lookup[date_str]['avg_cost']))
            else:
                cost_per_kwh.append(0.0)
        
        # Calculate actual efficiency (mi/kWh) for each day based on session data
        efficiency = []
        for d in daily_data:
            if d.total_kwh > 0:
                # Calculate actual efficiency for this day based on sessions
                daily_efficiency = DerivedMetricsService._calculate_daily_efficiency(user_id, d.date, car_id)
                efficiency.append(daily_efficiency)
            else:
                efficiency.append(0)
        
        # AC/DC split data
        ac_energy = [float(d.ac_kwh or 0) for d in ac_dc_data]
        dc_energy = [float(d.dc_kwh or 0) for d in ac_dc_data]
        
        # Calculate cost per mile for each day (requires car efficiency data)
        cost_per_mile = []
        # Use the same car logic for cost per mile
        if not car_id:
            available_car = Car.query.filter_by(user_id=user_id).first()
            # Use the same efficiency calculation as above
            dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id)
            car_efficiency = available_car.efficiency_mpkwh if available_car else None
            final_efficiency = dynamic_efficiency or car_efficiency
            
            if final_efficiency:
                for d in daily_data:
                    date_str = str(d.date)
                    if d.total_kwh > 0:
                        miles = d.total_kwh * final_efficiency
                        if date_str in cost_lookup:
                            daily_cost = cost_lookup[date_str]['daily_cost']
                            cost_per_mile.append(daily_cost / miles if miles > 0 else 0)
                        else:
                            # Free charging day
                            cost_per_mile.append(0)
                    else:
                        cost_per_mile.append(0)
            else:
                cost_per_mile = [0] * len(dates)
        else:
            car = Car.query.get(car_id)
            # Use the same efficiency calculation as above
            dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id, car_id)
            car_efficiency = car.efficiency_mpkwh if car else None
            final_efficiency = dynamic_efficiency or car_efficiency
            
            if final_efficiency:
                for d in daily_data:
                    date_str = str(d.date)
                    if d.total_kwh > 0:
                        miles = d.total_kwh * final_efficiency
                        if date_str in cost_lookup:
                            daily_cost = cost_lookup[date_str]['daily_cost']
                            cost_per_mile.append(daily_cost / miles if miles > 0 else 0)
                        else:
                            # Free charging day
                            cost_per_mile.append(0)
                    else:
                        cost_per_mile.append(0)
            else:
                cost_per_mile = [0] * len(dates)
        
        return {
            'dates': dates,
            'cost_per_kwh': cost_per_kwh,
            'cost_per_mile': cost_per_mile,
            'energy_delivered': energy_delivered,
            'ac_energy': ac_energy,
            'dc_energy': dc_energy,
            'efficiency': efficiency
        }

    @staticmethod
    def get_recommendations(user_id, active_car):
        """Get rule-based recommendations"""
        recommendations = []
        
        if not active_car:
            return recommendations
        
        # Check if 100% charge is overdue
        if active_car.recommended_full_charge_enabled:
            last_full_charge = ChargingSession.query.filter_by(
                user_id=user_id,
                car_id=active_car.id
            ).filter(ChargingSession.soc_to >= 95).order_by(ChargingSession.date.desc()).first()
            
            if last_full_charge:
                days_since_full = (datetime.now().date() - last_full_charge.date).days
                frequency_days = active_car.recommended_full_charge_frequency_value
                
                if active_car.recommended_full_charge_frequency_unit == 'months':
                    frequency_days = frequency_days * 30
                
                if days_since_full > frequency_days:
                    recommendations.append({
                        'type': 'warning',
                        'title': '100% Charge Overdue',
                        'message': f'100% charge overdue by {days_since_full - frequency_days} days',
                        'icon': 'bi-exclamation-triangle'
                    })
        
        # Check home vs public charging costs
        home_sessions = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == active_car.id,
                or_(
                    ChargingSession.location_label.ilike('%home%'),
                    ChargingSession.location_label.ilike('%garage%')
                )
            )
        ).all()
        
        public_sessions = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == active_car.id,
                not_(
                    or_(
                        ChargingSession.location_label.ilike('%home%'),
                        ChargingSession.location_label.ilike('%garage%')
                    )
                )
            )
        ).all()
        
        if home_sessions and public_sessions:
            avg_home_cost = sum(s.cost_per_kwh for s in home_sessions) / len(home_sessions)
            avg_public_cost = sum(s.cost_per_kwh for s in public_sessions) / len(public_sessions)
            
            if avg_home_cost < avg_public_cost:
                recommendations.append({
                    'type': 'info',
                    'title': 'Home Charging Advantage',
                    'message': f'Home charging is cheaper (£{avg_home_cost:.4f}/kWh vs £{avg_public_cost:.4f}/kWh average for public charging)',
                    'icon': 'bi-house'
                })
            else:
                recommendations.append({
                    'type': 'info',
                    'title': 'Public Charging Advantage',
                    'message': f'Public charging is cheaper (£{avg_public_cost:.4f}/kWh vs £{avg_home_cost:.4f}/kWh average for home charging)',
                    'icon': 'bi-lightning'
                })
        
        # Add general insights based on charging patterns
        total_sessions = ChargingSession.query.filter_by(user_id=user_id, car_id=active_car.id).count()
        
        if total_sessions >= 3:  # Only show after some data is collected
            # Check for free charging opportunities
            free_sessions = ChargingSession.query.filter(
                and_(
                    ChargingSession.user_id == user_id,
                    ChargingSession.car_id == active_car.id,
                    ChargingSession.cost_per_kwh == 0
                )
            ).count()
            
            if free_sessions > 0:
                recommendations.append({
                    'type': 'success',
                    'title': 'Free Charging Utilized',
                    'message': f'Great job! You\'ve had {free_sessions} free charging session(s). Keep an eye out for workplace, dealer, or public free charging opportunities.',
                    'icon': 'bi-gift'
                })
            
            # Check charging efficiency
            recent_sessions = ChargingSession.query.filter_by(
                user_id=user_id, 
                car_id=active_car.id
            ).order_by(ChargingSession.date.desc()).limit(5).all()
            
            if recent_sessions:
                avg_duration = sum(s.duration_mins for s in recent_sessions) / len(recent_sessions)
                avg_kwh = sum(s.charge_delivered_kwh for s in recent_sessions) / len(recent_sessions)
                
                if avg_kwh > 0:
                    avg_power = (avg_kwh / (avg_duration / 60))
                    
                    if avg_power < 3.0:  # Low power charging
                        recommendations.append({
                            'type': 'info',
                            'title': 'Slow Charging Detected',
                            'message': f'Your recent sessions average {avg_power:.1f} kW. Consider faster chargers for longer trips, or use slow charging for battery health.',
                            'icon': 'bi-speedometer'
                        })
                    elif avg_power > 20.0:  # High power charging
                        recommendations.append({
                            'type': 'info',
                            'title': 'Fast Charging Used',
                            'message': f'You\'re using fast chargers ({avg_power:.1f} kW average). Remember that frequent fast charging can impact battery longevity.',
                            'icon': 'bi-lightning-charge'
                        })
        
        # If no specific recommendations, provide general tips
        if not recommendations:
            recommendations.append({
                'type': 'info',
                'title': 'Getting Started',
                'message': 'Add more charging sessions to get personalized recommendations. Track your costs, locations, and charging patterns for better insights.',
                'icon': 'bi-info-circle'
            })
        
        return recommendations

    @staticmethod
    def calculate_dynamic_efficiency(user_id, car_id=None):
        """Calculate mi/kWh efficiency from historical charging session data"""
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get sessions with meaningful data (exclude very short sessions)
        sessions = query.filter(
            and_(
                ChargingSession.charge_delivered_kwh > 0.5,  # Exclude tiny sessions
                ChargingSession.duration_mins > 5  # Exclude very short sessions
            )
        ).order_by(ChargingSession.date.desc()).limit(20).all()  # Use last 20 sessions
        
        if not sessions:
            return None
        
        total_miles = 0
        total_kwh = 0
        
        for session in sessions:
            # Calculate miles based on SoC change and battery capacity
            if session.car and session.car.battery_kwh:
                soc_change = session.soc_to - session.soc_from
                if soc_change > 0:
                    # Estimate miles based on SoC change and battery capacity
                    # This assumes linear relationship between SoC and range
                    estimated_miles = (soc_change / 100) * session.car.battery_kwh * 4.0  # Rough estimate
                    total_miles += estimated_miles
                    total_kwh += session.charge_delivered_kwh
        
        if total_kwh > 0:
            efficiency = total_miles / total_kwh
            return round(efficiency, 2)
        
        return None

    @staticmethod
    def get_current_efficiency_info(user_id, car_id=None):
        """Get current efficiency information for display"""
        dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id, car_id)
        
        if car_id:
            car = Car.query.get(car_id)
            car_efficiency = car.efficiency_mpkwh if car else None
        else:
            available_car = Car.query.filter_by(user_id=user_id).first()
            car_efficiency = available_car.efficiency_mpkwh if available_car else None
        
        return {
            'dynamic_efficiency': dynamic_efficiency,
            'car_profile_efficiency': car_efficiency,
            'final_efficiency': dynamic_efficiency or car_efficiency,
            'source': 'dynamic' if dynamic_efficiency else 'car_profile' if car_efficiency else 'none'
        }

    @staticmethod
    def get_similar_sessions(session, limit=5):
        """Find similar sessions for comparison and delta calculations"""
        # Get sessions with same car and either:
        # 1. Same charge type and overlapping SoC window (±10% of soc_from), OR
        # 2. Same location/network
        
        # Build base query for same car
        base_query = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == session.user_id,
                ChargingSession.car_id == session.car_id,
                ChargingSession.id != session.id  # Exclude current session
            )
        )
        
        # Get sessions with same charge type and overlapping SoC window
        soc_window_query = base_query.filter(
            and_(
                ChargingSession.charge_type == session.charge_type,
                ChargingSession.soc_from >= max(0, session.soc_from - 10),
                ChargingSession.soc_from <= min(100, session.soc_from + 10)
            )
        ).order_by(ChargingSession.date.desc()).limit(limit)
        
        # Get sessions with same location/network
        location_query = base_query.filter(
            or_(
                ChargingSession.location_label.ilike(f'%{session.location_label}%'),
                ChargingSession.charge_network == session.charge_network
            )
        ).order_by(ChargingSession.date.desc()).limit(limit)
        
        # Combine and deduplicate results
        similar_sessions = []
        seen_ids = set()
        
        for s in soc_window_query.all():
            if s.id not in seen_ids:
                similar_sessions.append(s)
                seen_ids.add(s.id)
        
        for s in location_query.all():
            if s.id not in seen_ids and len(similar_sessions) < limit:
                similar_sessions.append(s)
                seen_ids.add(s.id)
        
        return similar_sessions[:limit]

    @staticmethod
    def get_rolling_averages(user_id, car_id, days=30):
        """Get rolling averages for comparison with current session"""
        from datetime import datetime, timedelta
        
        date_from = datetime.now().date() - timedelta(days=days)
        
        query = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == car_id,
                ChargingSession.date >= date_from
            )
        )
        
        # Calculate averages
        result = query.with_entities(
            func.avg(ChargingSession.charge_delivered_kwh).label('avg_kwh'),
            func.avg(ChargingSession.cost_per_kwh).label('avg_cost_per_kwh'),
            func.avg(ChargingSession.duration_mins).label('avg_duration_mins')
        ).first()
        
        # Get car for efficiency calculations
        car = Car.query.get(car_id)
        efficiency = car.efficiency_mpkwh if car else float(Settings.get_setting(user_id, 'default_efficiency_mpkwh', '3.7'))
        
        avg_kwh = result.avg_kwh or 0
        avg_cost_per_kwh = result.avg_cost_per_kwh or 0
        avg_duration_mins = result.avg_duration_mins or 0
        
        # Calculate derived averages
        avg_total_cost = avg_kwh * avg_cost_per_kwh
        avg_miles_gained = avg_kwh * efficiency
        avg_cost_per_mile = avg_total_cost / avg_miles_gained if avg_miles_gained > 0 else 0
        avg_power_kw = avg_kwh / (avg_duration_mins / 60) if avg_duration_mins > 0 else 0
        
        return {
            'avg_kwh': avg_kwh,
            'avg_cost_per_kwh': avg_cost_per_kwh,
            'avg_total_cost': avg_total_cost,
            'avg_miles_gained': avg_miles_gained,
            'avg_cost_per_mile': avg_cost_per_mile,
            'avg_power_kw': avg_power_kw,
            'avg_duration_mins': avg_duration_mins
        }

    @staticmethod
    def _calculate_daily_efficiency(user_id, date, car_id=None):
        """Calculate actual efficiency for a specific day based on session data with realistic variations"""
        # Build query for sessions on this date
        query = ChargingSession.query.filter_by(
            user_id=user_id,
            date=date
        )
        
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.all()
        
        if not sessions:
            return 0
        
        # Calculate weighted average efficiency with realistic variations
        total_kwh = 0
        weighted_efficiency_sum = 0
        
        for session in sessions:
            # Get car for this session
            car = Car.query.get(session.car_id)
            if not car:
                continue
                
            # Use car efficiency if available, otherwise skip this session
            if not car.efficiency_mpkwh:
                continue
            
            # Calculate realistic efficiency variations based on charging conditions
            base_efficiency = car.efficiency_mpkwh
            
            # Efficiency can vary based on:
            # 1. Charging speed (very fast DC charging might be slightly less efficient)
            # 2. Temperature (cold weather can reduce efficiency)
            # 3. Battery state (very low or very high SoC can affect efficiency)
            
            efficiency_multiplier = 1.0
            
            # DC charging at high speeds might be slightly less efficient
            if session.charge_type == 'DC' and session.charge_speed_kw > 50:
                efficiency_multiplier *= 0.98  # 2% reduction for very fast DC
            
            # Very low SoC charging might be less efficient
            if session.soc_from < 20:
                efficiency_multiplier *= 0.97  # 3% reduction for very low SoC
            
            # Very high SoC charging might be less efficient
            if session.soc_to > 90:
                efficiency_multiplier *= 0.96  # 4% reduction for very high SoC
            
            # Apply seasonal variation (simplified - could be enhanced with actual weather data)
            month = session.date.month
            if month in [12, 1, 2]:  # Winter months
                efficiency_multiplier *= 0.95  # 5% reduction in winter
            elif month in [6, 7, 8]:  # Summer months
                efficiency_multiplier *= 1.02  # 2% improvement in summer
            
            # Calculate adjusted efficiency for this session
            adjusted_efficiency = base_efficiency * efficiency_multiplier
            
            # Weight by kWh delivered (more kWh = more influence on daily average)
            session_weight = session.charge_delivered_kwh
            total_kwh += session_weight
            weighted_efficiency_sum += session_weight * adjusted_efficiency
        
        # Return weighted average efficiency
        if total_kwh > 0:
            return round(weighted_efficiency_sum / total_kwh, 2)
        else:
            return 0
