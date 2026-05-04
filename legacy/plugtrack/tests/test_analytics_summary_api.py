#!/usr/bin/env python3
"""
Unit tests for PlugTrack Phase 6 Stage A - Analytics Summary API
Tests the /api/analytics/summary endpoint
"""

import unittest
import sys
import os
import json
from datetime import datetime, timedelta, date

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from __init__ import create_app, db
from models.user import User
from models.car import Car
from models.charging_session import ChargingSession
from models.settings import Settings
from services.analytics_agg import AnalyticsAggService


class TestAnalyticsSummaryApi(unittest.TestCase):
    """Test cases for /api/analytics/summary endpoint"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        # Generate unique username
        import uuid
        unique_suffix = uuid.uuid4().hex[:8]
        self.username = f'testuser_summary_{unique_suffix}'
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.user = User(username=self.username)
            self.user.set_password('testpass')
            db.session.add(self.user)
            db.session.commit()
            self.user_id = self.user.id
            
            # Create test car
            self.car = Car(
                user_id=self.user_id,
                make='Tesla',
                model='Model 3',
                battery_kwh=75.0,
                efficiency_mpkwh=4.2,
                active=True
            )
            db.session.add(self.car)
            db.session.commit()
            self.car_id = self.car.id
            
            # Create default settings
            default_settings = [
                ('petrol_price_p_per_litre', '128.9'),
                ('petrol_mpg', '60.0'),
                ('default_efficiency_mpkwh', '4.1'),
                ('home_aliases_csv', 'home,house,garage'),
                ('home_charging_speed_kw', '7.4')
            ]
            
            for key, value in default_settings:
                setting = Settings(user_id=self.user_id, key=key, value=value)
                db.session.add(setting)
            
            db.session.commit()
            
            # Create test client
            self.client = self.app.test_client()
    
    def tearDown(self):
        """Clean up after tests"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def login_user(self):
        """Helper to log in test user"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True
    
    def create_sample_sessions(self):
        """Create sample charging sessions for testing"""
        with self.app.app_context():
            sessions_data = [
                # Home charging session - cheapest
                {
                    'date': date.today() - timedelta(days=10),
                    'odometer': 15000,
                    'charge_type': 'AC',
                    'charge_speed_kw': 7.4,
                    'location_label': 'Home',
                    'charge_network': 'Home Charger',
                    'charge_delivered_kwh': 25.5,
                    'duration_mins': 300,
                    'cost_per_kwh': 0.08,  # Very cheap
                    'soc_from': 20,
                    'soc_to': 54,
                    'venue_type': 'home',
                    'is_baseline': False,  # Make non-baseline for efficiency calculation
                    'ambient_temp_c': 18.5
                },
                # Public DC charging session - most expensive
                {
                    'date': date.today() - timedelta(days=5),
                    'odometer': 15100,
                    'charge_type': 'DC',
                    'charge_speed_kw': 150.0,
                    'location_label': 'Motorway Services',
                    'charge_network': 'Ionity',
                    'charge_delivered_kwh': 45.0,
                    'duration_mins': 30,
                    'cost_per_kwh': 0.79,  # Very expensive
                    'soc_from': 10,
                    'soc_to': 80,
                    'venue_type': 'public',
                    'is_baseline': False,  # Make non-baseline for efficiency calculation
                    'ambient_temp_c': 22.0
                },
                # Another home session
                {
                    'date': date.today() - timedelta(days=2),
                    'odometer': 15200,
                    'charge_type': 'AC',
                    'charge_speed_kw': 7.4,
                    'location_label': 'Home',
                    'charge_network': 'Home Charger',
                    'charge_delivered_kwh': 30.0,
                    'duration_mins': 240,
                    'cost_per_kwh': 0.09,
                    'soc_from': 25,
                    'soc_to': 65,
                    'venue_type': 'home',
                    'is_baseline': False,  # Make non-baseline for efficiency calculation
                    'ambient_temp_c': 15.0
                }
            ]
            
            for session_data in sessions_data:
                session = ChargingSession(
                    user_id=self.user_id,
                    car_id=self.car_id,
                    **session_data
                )
                db.session.add(session)
            
            db.session.commit()
    
    def test_analytics_summary_endpoint_requires_auth(self):
        """Test that the analytics summary endpoint requires authentication"""
        response = self.client.get('/api/analytics/summary')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_analytics_summary_with_no_data(self):
        """Test analytics summary endpoint with no charging sessions"""
        self.login_user()
        response = self.client.get('/api/analytics/summary')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        # Should return structure with zero/null values
        expected_structure = {
            'weighted_efficiency',
            'lifetime',
            'most_expensive',
            'cheapest'
        }
        self.assertTrue(expected_structure.issubset(set(data.keys())))
        
        # Check lifetime totals are zero/null
        lifetime = data['lifetime']
        self.assertEqual(lifetime['kwh'], 0)
        self.assertEqual(lifetime['miles'], 0)
        self.assertEqual(lifetime['cost'], 0)
    
    def test_analytics_summary_with_data(self):
        """Test analytics summary endpoint with sample data"""
        self.create_sample_sessions()
        self.login_user()
        
        response = self.client.get('/api/analytics/summary')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        
        # Verify structure
        expected_structure = {
            'weighted_efficiency',
            'lifetime',
            'most_expensive',
            'cheapest'
        }
        self.assertTrue(expected_structure.issubset(set(data.keys())))
        
        # Check lifetime totals
        lifetime = data['lifetime']
        self.assertGreater(lifetime['kwh'], 0)
        self.assertGreater(lifetime['miles'], 0)
        self.assertGreater(lifetime['cost'], 0)
        self.assertIsNotNone(lifetime['saved_vs_petrol'])
        
        # Check weighted efficiency
        self.assertIsInstance(data['weighted_efficiency'], (int, float))
        self.assertGreater(data['weighted_efficiency'], 0)
        
        # Check most expensive session
        most_expensive = data['most_expensive']
        self.assertIsNotNone(most_expensive)
        self.assertIn('id', most_expensive)
        self.assertIn('p_per_mi', most_expensive)
        self.assertIn('date', most_expensive)
        
        # Check cheapest session
        cheapest = data['cheapest']
        self.assertIsNotNone(cheapest)
        self.assertIn('id', cheapest)
        self.assertIn('p_per_mi', cheapest)
        self.assertIn('date', cheapest)
        
        # Cheapest should have lower p/mi than most expensive
        self.assertLess(cheapest['p_per_mi'], most_expensive['p_per_mi'])
    
    def test_analytics_summary_car_filter(self):
        """Test analytics summary endpoint with car filter"""
        self.create_sample_sessions()
        self.login_user()
        
        # Test with valid car ID
        response = self.client.get(f'/api/analytics/summary?car_id={self.car_id}')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertIn('lifetime', data)
        self.assertGreater(data['lifetime']['kwh'], 0)
        
        # Test with invalid car ID  
        response = self.client.get('/api/analytics/summary?car_id=99999')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        # Should return empty/zero data for non-existent car
        self.assertEqual(data['lifetime']['kwh'], 0)
    
    def test_analytics_summary_json_format(self):
        """Test that analytics summary returns proper JSON format"""
        self.create_sample_sessions()
        self.login_user()
        
        response = self.client.get('/api/analytics/summary')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'application/json')
        
        # Should be valid JSON
        data = json.loads(response.data)
        self.assertIsInstance(data, dict)
    
    def test_analytics_summary_service_direct(self):
        """Test the AnalyticsAggService directly"""
        self.create_sample_sessions()
        
        with self.app.app_context():
            summary = AnalyticsAggService.get_analytics_summary(self.user_id)
            
            # Verify service returns expected structure
            expected_keys = {'weighted_efficiency', 'lifetime', 'most_expensive', 'cheapest'}
            self.assertTrue(expected_keys.issubset(set(summary.keys())))
            
            # Verify weighted efficiency calculation
            self.assertIsInstance(summary['weighted_efficiency'], (int, float))
            
            # Verify lifetime calculations
            lifetime = summary['lifetime']
            required_lifetime_keys = {'kwh', 'miles', 'cost', 'saved_vs_petrol'}
            self.assertTrue(required_lifetime_keys.issubset(set(lifetime.keys())))
            
            # Verify cost extremes
            if summary['most_expensive']:
                self.assertIn('p_per_mi', summary['most_expensive'])
            if summary['cheapest']:
                self.assertIn('p_per_mi', summary['cheapest'])


if __name__ == '__main__':
    unittest.main()
