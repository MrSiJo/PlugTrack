#!/usr/bin/env python3
"""
Phase 5 Metrics Consistency Tests - validates aggregated analytics and reminder logic.
"""

import os
import sys
import unittest
from datetime import date, timedelta

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from __init__ import create_app, db
from models import User, Car, ChargingSession
from services.aggregated_analytics import AggregatedAnalyticsService
from services.reminders import ReminderService
from services.derived_metrics import DerivedMetricsService


class TestPhase5Metrics(unittest.TestCase):
    """Test Phase 5 metrics consistency"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        
        # Create test user and car
        self.user = User(username='test', password_hash='test')
        db.session.add(self.user)
        db.session.commit()
        
        self.car = Car(
            user_id=self.user.id,
            make='Test', model='EV',
            battery_kwh=50.0, efficiency_mpkwh=3.5,
            active=True,
            recommended_full_charge_enabled=True,
            recommended_full_charge_frequency_value=7,
            recommended_full_charge_frequency_unit='days'
        )
        db.session.add(self.car)
        db.session.commit()
        
        # Create test sessions
        self.create_test_data()
    
    def tearDown(self):
        """Clean up"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
    
    def create_test_data(self):
        """Create test charging sessions"""
        sessions = [
            # Home charging
            {'date': date.today() - timedelta(days=20), 'kwh': 20.0, 'cost': 0.10, 'soc_to': 80},
            # DC charging  
            {'date': date.today() - timedelta(days=15), 'kwh': 25.0, 'cost': 0.45, 'soc_to': 85},
            # 100% charge
            {'date': date.today() - timedelta(days=10), 'kwh': 15.0, 'cost': 0.12, 'soc_to': 100},
            # Recent charge
            {'date': date.today() - timedelta(days=2), 'kwh': 12.0, 'cost': 0.11, 'soc_to': 70}
        ]
        
        for i, data in enumerate(sessions):
            session = ChargingSession(
                user_id=self.user.id, car_id=self.car.id,
                date=data['date'], odometer=1000 + i*100,
                charge_type='DC' if data['cost'] > 0.2 else 'AC',
                charge_speed_kw=50.0 if data['cost'] > 0.2 else 7.4,
                location_label='Motorway' if data['cost'] > 0.2 else 'Home',
                charge_delivered_kwh=data['kwh'], duration_mins=120,
                cost_per_kwh=data['cost'], soc_from=30, soc_to=data['soc_to']
            )
            db.session.add(session)
        db.session.commit()
    
    def test_lifetime_totals_consistency(self):
        """Test aggregated totals match individual session calculations"""
        # Calculate individual totals
        sessions = ChargingSession.query.filter_by(user_id=self.user.id).all()
        individual_cost = sum(s.charge_delivered_kwh * s.cost_per_kwh for s in sessions)
        individual_kwh = sum(s.charge_delivered_kwh for s in sessions)
        
        # Get aggregated totals
        totals = AggregatedAnalyticsService.get_lifetime_totals(self.user.id)
        
        # Verify consistency
        self.assertAlmostEqual(totals['total_cost_gbp'], individual_cost, places=2)
        self.assertEqual(totals['total_kwh'], individual_kwh)
        self.assertEqual(totals['total_sessions'], len(sessions))
    
    def test_best_worst_sessions_logic(self):
        """Test best/worst session identification logic"""
        best_worst = AggregatedAnalyticsService.get_best_worst_sessions(self.user.id)
        
        # Verify structure
        required_keys = ['cheapest_per_mile', 'most_expensive_per_mile', 'fastest_session', 
                        'slowest_session', 'largest_session_kwh', 'smallest_session_kwh']
        for key in required_keys:
            self.assertIn(key, best_worst)
        
        # Verify largest session is the 25kWh DC session
        largest = best_worst['largest_session_kwh']
        self.assertEqual(largest['kwh'], 25.0)
        
        # Verify smallest session is the 12kWh session
        smallest = best_worst['smallest_session_kwh']
        self.assertEqual(smallest['kwh'], 12.0)
    
    def test_reminder_logic_consistency(self):
        """Test reminder calculation logic"""
        # Should have reminder (last 100% was 10 days ago, frequency is 7 days)
        reminders = ReminderService.check_full_charge_due(self.user.id, self.car.id)
        
        self.assertEqual(reminders['reminders_due'], 1)
        reminder = reminders['reminders'][0]
        self.assertEqual(reminder['car_id'], self.car.id)
        self.assertEqual(reminder['days_overdue'], 3)  # 10 - 7 = 3
        self.assertEqual(reminder['urgency'], 'due')  # 3 days overdue = 'due'
    
    def test_seasonal_temperature_buckets(self):
        """Test temperature bucketing works correctly"""
        # Add sessions with specific temperatures
        temp_session = ChargingSession(
            user_id=self.user.id, car_id=self.car.id,
            date=date.today() - timedelta(days=5), odometer=1500,
            charge_type='AC', charge_speed_kw=7.4, location_label='Test',
            charge_delivered_kwh=10.0, duration_mins=90,
            cost_per_kwh=0.10, soc_from=40, soc_to=60,
            ambient_temp_c=18.0  # Should be in 'mild' bucket (15-25°C)
        )
        db.session.add(temp_session)
        db.session.commit()
        
        seasonal = AggregatedAnalyticsService.get_seasonal_averages(self.user.id)
        
        # Verify mild bucket has the session
        self.assertEqual(seasonal['mild']['count'], 1)
        self.assertAlmostEqual(seasonal['mild']['avg_temp_c'], 18.0, places=1)


if __name__ == '__main__':
    unittest.main()
