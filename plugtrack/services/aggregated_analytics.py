#!/usr/bin/env python3
"""
Aggregated Analytics Service for PlugTrack Phase 5-4.

Provides lifetime totals, best/worst sessions, and seasonal averages.
Backend service only - no UI components in this phase.
"""

from typing import Dict, List, Any, Optional
from sqlalchemy import func, case, and_
from datetime import datetime

from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from services.derived_metrics import DerivedMetricsService
from utils.petrol_calculations import get_petrol_threshold_for_user


class AggregatedAnalyticsService:
    """Service for aggregated statistics and analytics"""
    
    # Temperature buckets for seasonal analysis (Celsius)
    TEMP_BUCKETS = [
        ('very_cold', -10, 5),      # -10°C to 5°C
        ('cold', 5, 15),            # 5°C to 15°C  
        ('mild', 15, 25),           # 15°C to 25°C
        ('warm', 25, 35),           # 25°C to 35°C
        ('hot', 35, 50)             # 35°C to 50°C
    ]
    
    @staticmethod
    def get_lifetime_totals(user_id: int, car_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get lifetime totals for a user or specific car.
        
        Args:
            user_id: User ID
            car_id: Optional car ID filter
            
        Returns:
            Dict with lifetime totals: kWh, miles, £, £ saved vs petrol
        """
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get basic totals
        totals = query.with_entities(
            func.sum(ChargingSession.charge_delivered_kwh).label('total_kwh'),
            func.sum(ChargingSession.charge_delivered_kwh * ChargingSession.cost_per_kwh).label('total_cost_gbp'),
            func.count(ChargingSession.id).label('total_sessions')
        ).first()
        
        total_kwh = float(totals.total_kwh or 0)
        total_cost_gbp = float(totals.total_cost_gbp or 0)
        total_sessions = int(totals.total_sessions or 0)
        
        # Calculate total miles using efficiency data
        total_miles = 0
        if total_sessions > 0:
            # Get sessions with their cars for efficiency calculation
            sessions = query.join(Car).all()
            for session in sessions:
                car = Car.query.get(session.car_id)
                metrics = DerivedMetricsService.calculate_session_metrics(session, car)
                total_miles += metrics.get('miles_gained', 0)
        
        # Calculate petrol savings
        total_petrol_cost_gbp = 0
        if total_miles > 0:
            # Get user's petrol comparison settings
            petrol_price_p_per_litre = float(Settings.get_setting(user_id, 'petrol_price_p_per_litre', '128.9'))
            petrol_mpg = float(Settings.get_setting(user_id, 'petrol_mpg', '60.0'))
            
            # Calculate equivalent petrol cost
            gallons_needed = total_miles / petrol_mpg
            total_petrol_cost_gbp = (gallons_needed * petrol_price_p_per_litre * 4.546) / 100  # Convert pence to pounds
        
        savings_gbp = total_petrol_cost_gbp - total_cost_gbp
        
        return {
            'total_kwh': round(total_kwh, 2),
            'total_miles': round(total_miles, 1),
            'total_cost_gbp': round(total_cost_gbp, 2),
            'total_petrol_equivalent_gbp': round(total_petrol_cost_gbp, 2),
            'savings_vs_petrol_gbp': round(savings_gbp, 2),
            'total_sessions': total_sessions,
            'avg_cost_per_kwh': round(total_cost_gbp / total_kwh, 3) if total_kwh > 0 else 0,
            'avg_cost_per_mile': round(total_cost_gbp / total_miles, 3) if total_miles > 0 else 0
        }
    
    @staticmethod
    def get_best_worst_sessions(user_id: int, car_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get best and worst sessions across various metrics.
        
        Args:
            user_id: User ID
            car_id: Optional car ID filter
            
        Returns:
            Dict with best/worst sessions for different metrics
        """
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.join(Car).all()
        
        if not sessions:
            return {
                'cheapest_per_mile': None,
                'most_expensive_per_mile': None,
                'fastest_session': None,
                'slowest_session': None,
                'most_efficient': None,
                'least_efficient': None,
                'largest_session_kwh': None,
                'smallest_session_kwh': None
            }
        
        # Calculate metrics for all sessions
        session_metrics = []
        for session in sessions:
            car = Car.query.get(session.car_id)
            metrics = DerivedMetricsService.calculate_session_metrics(session, car)
            
            session_data = {
                'session': session,
                'cost_per_mile': metrics.get('cost_per_mile', 0),
                'avg_power_kw': metrics.get('avg_power_kw', 0),
                'efficiency_used': metrics.get('efficiency_used', 0),
                'kwh': session.charge_delivered_kwh,
                'date': session.date,
                'location': session.location_label
            }
            session_metrics.append(session_data)
        
        # Filter out sessions with zero cost_per_mile (free charging or no efficiency)
        valid_cost_sessions = [s for s in session_metrics if s['cost_per_mile'] > 0]
        valid_efficiency_sessions = [s for s in session_metrics if s['efficiency_used'] is not None and s['efficiency_used'] > 0]
        valid_power_sessions = [s for s in session_metrics if s['avg_power_kw'] > 0]
        
        def format_session_summary(session_data):
            if not session_data:
                return None
            return {
                'id': session_data['session'].id,
                'date': session_data['date'].isoformat(),
                'location': session_data['location'],
                'kwh': session_data['kwh'],
                'cost_per_mile': session_data['cost_per_mile'],
                'avg_power_kw': session_data['avg_power_kw'],
                'efficiency_used': session_data['efficiency_used']
            }
        
        # Find best/worst sessions
        cheapest = min(valid_cost_sessions, key=lambda x: x['cost_per_mile']) if valid_cost_sessions else None
        most_expensive = max(valid_cost_sessions, key=lambda x: x['cost_per_mile']) if valid_cost_sessions else None
        fastest = max(valid_power_sessions, key=lambda x: x['avg_power_kw']) if valid_power_sessions else None
        slowest = min(valid_power_sessions, key=lambda x: x['avg_power_kw']) if valid_power_sessions else None
        most_efficient = max(valid_efficiency_sessions, key=lambda x: x['efficiency_used']) if valid_efficiency_sessions else None
        least_efficient = min(valid_efficiency_sessions, key=lambda x: x['efficiency_used']) if valid_efficiency_sessions else None
        largest = max(session_metrics, key=lambda x: x['kwh'])
        smallest = min(session_metrics, key=lambda x: x['kwh'])
        
        return {
            'cheapest_per_mile': format_session_summary(cheapest),
            'most_expensive_per_mile': format_session_summary(most_expensive),
            'fastest_session': format_session_summary(fastest),
            'slowest_session': format_session_summary(slowest),
            'most_efficient': format_session_summary(most_efficient),
            'least_efficient': format_session_summary(least_efficient),
            'largest_session_kwh': format_session_summary(largest),
            'smallest_session_kwh': format_session_summary(smallest)
        }
    
    @staticmethod
    def get_seasonal_averages(user_id: int, car_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get seasonal averages based on ambient temperature buckets.
        
        Args:
            user_id: User ID
            car_id: Optional car ID filter
            
        Returns:
            Dict with seasonal averages by temperature bucket
        """
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Only include sessions with ambient temperature data
        query = query.filter(ChargingSession.ambient_temp_c.isnot(None))
        
        sessions = query.join(Car).all()
        
        if not sessions:
            return {bucket[0]: {'count': 0, 'avg_efficiency': 0, 'avg_cost_per_mile': 0, 'avg_power_kw': 0} 
                    for bucket in AggregatedAnalyticsService.TEMP_BUCKETS}
        
        # Group sessions by temperature buckets
        buckets = {}
        for bucket_name, min_temp, max_temp in AggregatedAnalyticsService.TEMP_BUCKETS:
            buckets[bucket_name] = {
                'sessions': [],
                'min_temp': min_temp,
                'max_temp': max_temp
            }
        
        # Classify sessions into buckets
        for session in sessions:
            temp = session.ambient_temp_c
            for bucket_name, min_temp, max_temp in AggregatedAnalyticsService.TEMP_BUCKETS:
                if min_temp <= temp < max_temp:
                    buckets[bucket_name]['sessions'].append(session)
                    break
        
        # Calculate averages for each bucket
        results = {}
        for bucket_name, bucket_data in buckets.items():
            bucket_sessions = bucket_data['sessions']
            count = len(bucket_sessions)
            
            if count == 0:
                results[bucket_name] = {
                    'count': 0,
                    'avg_efficiency': 0,
                    'avg_cost_per_mile': 0,
                    'avg_power_kw': 0,
                    'avg_temp_c': 0,
                    'temp_range': f"{bucket_data['min_temp']}°C to {bucket_data['max_temp']}°C"
                }
                continue
            
            # Calculate metrics for bucket sessions
            total_efficiency = 0
            total_cost_per_mile = 0
            total_power = 0
            total_temp = 0
            valid_efficiency_count = 0
            valid_cost_count = 0
            valid_power_count = 0
            
            for session in bucket_sessions:
                car = Car.query.get(session.car_id)
                metrics = DerivedMetricsService.calculate_session_metrics(session, car)
                
                efficiency = metrics.get('efficiency_used', 0)
                cost_per_mile = metrics.get('cost_per_mile', 0)
                power = metrics.get('avg_power_kw', 0)
                
                if efficiency is not None and efficiency > 0:
                    total_efficiency += efficiency
                    valid_efficiency_count += 1
                
                if cost_per_mile > 0:
                    total_cost_per_mile += cost_per_mile
                    valid_cost_count += 1
                
                if power > 0:
                    total_power += power
                    valid_power_count += 1
                
                total_temp += session.ambient_temp_c
            
            results[bucket_name] = {
                'count': count,
                'avg_efficiency': round(total_efficiency / valid_efficiency_count, 2) if valid_efficiency_count > 0 else 0,
                'avg_cost_per_mile': round(total_cost_per_mile / valid_cost_count, 3) if valid_cost_count > 0 else 0,
                'avg_power_kw': round(total_power / valid_power_count, 1) if valid_power_count > 0 else 0,
                'avg_temp_c': round(total_temp / count, 1),
                'temp_range': f"{bucket_data['min_temp']}°C to {bucket_data['max_temp']}°C"
            }
        
        return results
    
    @staticmethod
    def get_all_aggregated_stats(user_id: int, car_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get all aggregated statistics in one call.
        
        Args:
            user_id: User ID
            car_id: Optional car ID filter
            
        Returns:
            Dict containing all aggregated analytics
        """
        return {
            'lifetime_totals': AggregatedAnalyticsService.get_lifetime_totals(user_id, car_id),
            'best_worst_sessions': AggregatedAnalyticsService.get_best_worst_sessions(user_id, car_id),
            'seasonal_averages': AggregatedAnalyticsService.get_seasonal_averages(user_id, car_id),
            'generated_at': datetime.utcnow().isoformat()
        }
