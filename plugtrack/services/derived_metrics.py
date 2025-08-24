from models.charging_session import ChargingSession
from models.car import Car
from sqlalchemy import func, and_, or_, not_
from datetime import datetime, timedelta
import pandas as pd

class DerivedMetricsService:
    """Service for calculating derived metrics from charging session data"""

    @staticmethod
    def calculate_session_metrics(session, car):
        """Calculate metrics for a single charging session"""
        # Total cost
        total_cost = session.charge_delivered_kwh * session.cost_per_kwh
        
        # Miles gained (estimated based on car efficiency)
        miles_gained = 0
        if car and car.efficiency_mpkwh:
            miles_gained = session.charge_delivered_kwh * car.efficiency_mpkwh
        
        # Cost per mile
        cost_per_mile = 0
        if miles_gained > 0:
            cost_per_mile = total_cost / miles_gained
        
        # Battery added percentage
        battery_added_percent = session.soc_to - session.soc_from
        
        # Home vs public charging
        is_home_charging = 'home' in session.location_label.lower() or 'garage' in session.location_label.lower()
        
        return {
            'total_cost': total_cost,
            'miles_gained': miles_gained,
            'cost_per_mile': cost_per_mile,
            'battery_added_percent': battery_added_percent,
            'is_home_charging': is_home_charging
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
        if car_id:
            car = Car.query.get(car_id)
            if car and car.efficiency_mpkwh:
                total_miles = total_kwh * car.efficiency_mpkwh
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
            func.sum(ChargingSession.charge_delivered_kwh).filter(ChargingSession.charge_type == 'AC').label('ac_kwh'),
            func.sum(ChargingSession.charge_delivered_kwh).filter(ChargingSession.charge_type == 'DC').label('dc_kwh')
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
        
        # Calculate actual efficiency (mi/kWh) for each day
        efficiency = []
        if car_id:
            car = Car.query.get(car_id)
            if car and car.efficiency_mpkwh:
                for d in daily_data:
                    if d.total_kwh > 0:
                        # Use the car's efficiency rating
                        efficiency.append(car.efficiency_mpkwh)
                    else:
                        efficiency.append(0)
            else:
                efficiency = [0] * len(dates)
        else:
            efficiency = [0] * len(dates)
        
        # AC/DC split data
        ac_energy = [float(d.ac_kwh or 0) for d in ac_dc_data]
        dc_energy = [float(d.dc_kwh or 0) for d in ac_dc_data]
        
        # Calculate cost per mile for each day (requires car efficiency data)
        cost_per_mile = []
        if car_id:
            car = Car.query.get(car_id)
            if car and car.efficiency_mpkwh:
                for d in daily_data:
                    date_str = str(d.date)
                    if d.total_kwh > 0:
                        miles = d.total_kwh * car.efficiency_mpkwh
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
                    'message': f'Home charging is cheaper (£{avg_home_cost:.2f}/kWh vs £{avg_public_cost:.2f}/kWh)',
                    'icon': 'bi-house'
                })
            else:
                recommendations.append({
                    'type': 'info',
                    'title': 'Public Charging Advantage',
                    'message': f'Public charging is cheaper (£{avg_public_cost:.2f}/kWh vs £{avg_home_cost:.2f}/kWh)',
                    'icon': 'bi-lightning'
                })
        
        return recommendations
