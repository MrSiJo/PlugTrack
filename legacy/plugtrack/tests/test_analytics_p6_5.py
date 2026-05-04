"""
Unit tests for Analytics P6-5 charts
Tests the seasonal, leaderboard, and SoC sweet spot analytics.
"""

import unittest
import tempfile
import os
from datetime import datetime, date, timedelta
from __init__ import create_app
from models.user import db, User
from models.car import Car
from models.charging_session import ChargingSession
from services.analytics_agg import AnalyticsAggService


class TestAnalyticsP6_5(unittest.TestCase):
    """Test P6-5 analytics charts"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        # Use temporary file for test database
        db_fd, db_path = tempfile.mkstemp()
        os.close(db_fd)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        self.db_path = db_path
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.user = User(username='testuser', password_hash='hash')
            db.session.add(self.user)
            db.session.commit()
            
            # Create test car
            self.car = Car(
                user_id=self.user.id,
                make='Tesla',
                model='Model 3',
                year=2023,
                efficiency_mpkwh=4.0
            )
            db.session.add(self.car)
            db.session.commit()
            
        self.client = self.app.test_client()
    
    def tearDown(self):
        """Clean up test fixtures"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        
        if hasattr(self, 'db_path') and os.path.exists(self.db_path):
            os.unlink(self.db_path)
    
    def test_seasonal_analytics_api(self):
        """Test seasonal efficiency vs temperature API endpoint"""
        with self.app.app_context():
            # Create sessions with varying temperatures
            sessions = [
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=10),
                    charge_delivered_kwh=40.0,
                    cost_per_kwh=0.25,
                    ambient_temp_c=5,  # Cold
                    location_label='Home',
                    charge_type='AC',
                    soc_from=20,
                    soc_to=80,
                    odometer=10000
                ),
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=5),
                    charge_delivered_kwh=35.0,
                    cost_per_kwh=0.30,
                    ambient_temp_c=20,  # Moderate
                    location_label='Public',
                    charge_type='AC',
                    soc_from=30,
                    soc_to=85,
                    odometer=10200
                ),
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=1),
                    charge_delivered_kwh=30.0,
                    cost_per_kwh=0.20,
                    ambient_temp_c=25,  # Warm
                    location_label='Home',
                    charge_type='AC',
                    soc_from=40,
                    soc_to=90,
                    odometer=10350
                )
            ]
            
            for session in sessions:
                db.session.add(session)
            db.session.commit()
            
            # Mock login
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.user.id)
                sess['_fresh'] = True
            
            # Test seasonal API
            response = self.client.get('/api/analytics/seasonal')
            self.assertEqual(response.status_code, 200)
            
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertIn('temperature_efficiency', data)
    
    def test_leaderboard_analytics_api(self):
        """Test location leaderboard API endpoint"""
        with self.app.app_context():
            # Create sessions at different locations
            sessions = [
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=10),
                    charge_delivered_kwh=40.0,
                    cost_per_kwh=0.15,  # Cheap home charging
                    location_label='Home',
                    charge_type='AC',
                    soc_from=20,
                    soc_to=80,
                    odometer=10000
                ),
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=8),
                    charge_delivered_kwh=25.0,
                    cost_per_kwh=0.15,  # Another cheap home session
                    location_label='Home',
                    charge_type='AC',
                    soc_from=30,
                    soc_to=75,
                    odometer=10100
                ),
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=5),
                    charge_delivered_kwh=30.0,
                    cost_per_kwh=0.45,  # Expensive rapid charging
                    location_label='Motorway Services',
                    charge_type='DC',
                    soc_from=25,
                    soc_to=80,
                    odometer=10250
                ),
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=2),
                    charge_delivered_kwh=35.0,
                    cost_per_kwh=0.25,  # Medium cost public
                    location_label='Tesco Car Park',
                    charge_type='AC',
                    soc_from=40,
                    soc_to=85,
                    odometer=10400
                )
            ]
            
            for session in sessions:
                db.session.add(session)
            db.session.commit()
            
            # Mock login
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.user.id)
                sess['_fresh'] = True
            
            # Test leaderboard API
            response = self.client.get('/api/analytics/leaderboard')
            self.assertEqual(response.status_code, 200)
            
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertIn('locations', data)
            
            locations = data['locations']
            self.assertGreater(len(locations), 0)
            
            # Check that locations have required fields
            for location in locations:
                self.assertIn('name', location)
                self.assertIn('avg_cost_per_mile', location)
                self.assertIn('session_count', location)
    
    def test_soc_sweetspot_analytics_api(self):
        """Test SoC sweet spot API endpoint"""
        with self.app.app_context():
            # Create sessions with different SoC windows
            sessions = [
                # Low SoC charging (0-40%)
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=10),
                    charge_delivered_kwh=30.0,
                    cost_per_kwh=0.25,
                    location_label='Home',
                    charge_type='AC',
                    soc_from=10,
                    soc_to=40,
                    odometer=10000
                ),
                # Mid SoC charging (20-60%)
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=7),
                    charge_delivered_kwh=35.0,
                    cost_per_kwh=0.30,
                    location_label='Public',
                    charge_type='AC',
                    soc_from=20,
                    soc_to=60,
                    odometer=10150
                ),
                # High SoC charging (60-90%)
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=3),
                    charge_delivered_kwh=25.0,
                    cost_per_kwh=0.20,
                    location_label='Home',
                    charge_type='AC',
                    soc_from=60,
                    soc_to=90,
                    odometer=10300
                )
            ]
            
            for session in sessions:
                db.session.add(session)
            db.session.commit()
            
            # Mock login
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.user.id)
                sess['_fresh'] = True
            
            # Test sweet spot API
            response = self.client.get('/api/analytics/sweetspot')
            self.assertEqual(response.status_code, 200)
            
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertIn('soc_windows', data)
            
            # Check structure of SoC windows
            if data['soc_windows']:
                soc_window = data['soc_windows'][0]
                self.assertIn('soc_range', soc_window)
                self.assertIn('avg_efficiency', soc_window)
                self.assertIn('session_count', soc_window)
    
    def test_analytics_page_includes_p6_5_charts(self):
        """Test that analytics page includes the new P6-5 chart elements"""
        with self.app.app_context():
            # Create some test data
            session = ChargingSession(
                user_id=self.user.id,
                car_id=self.car.id,
                date=date.today(),
                charge_delivered_kwh=40.0,
                cost_per_kwh=0.25,
                ambient_temp_c=15,
                location_label='Test Location',
                charge_type='AC',
                soc_from=20,
                soc_to=80,
                odometer=10000
            )
            db.session.add(session)
            db.session.commit()
            
            # Mock login
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.user.id)
                sess['_fresh'] = True
            
            # Test analytics page
            response = self.client.get('/analytics')
            self.assertEqual(response.status_code, 200)
            
            content = response.data.decode('utf-8')
            
            # Check for P6-5 chart elements
            self.assertIn('Advanced Analytics', content)
            self.assertIn('Seasonal Efficiency vs Temperature', content)
            self.assertIn('Location Leaderboard', content)
            self.assertIn('SoC Sweet Spot', content)
            
            # Check for chart canvas elements
            self.assertIn('seasonalTempChart', content)
            self.assertIn('locationLeaderboardChart', content)
            self.assertIn('socSweetSpotChart', content)
            
            # Check for API fetch calls
            self.assertIn('/api/analytics/seasonal', content)
            self.assertIn('/api/analytics/leaderboard', content)
            self.assertIn('/api/analytics/sweetspot', content)
    
    def test_seasonal_analytics_with_no_temperature_data(self):
        """Test seasonal analytics when no temperature data is available"""
        with self.app.app_context():
            # Create session without temperature data
            session = ChargingSession(
                user_id=self.user.id,
                car_id=self.car.id,
                date=date.today(),
                charge_delivered_kwh=40.0,
                cost_per_kwh=0.25,
                ambient_temp_c=None,  # No temperature data
                location_label='Home',
                charge_type='AC',
                soc_from=20,
                soc_to=80,
                odometer=10000
            )
            db.session.add(session)
            db.session.commit()
            
            # Mock login
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.user.id)
                sess['_fresh'] = True
            
            # Test seasonal API with no temperature data
            response = self.client.get('/api/analytics/seasonal')
            self.assertEqual(response.status_code, 200)
            
            data = response.get_json()
            self.assertIsNotNone(data)
            # Should handle gracefully when no temperature data available
    
    def test_api_endpoints_require_authentication(self):
        """Test that P6-5 API endpoints require authentication"""
        # Test without login
        endpoints = [
            '/api/analytics/seasonal',
            '/api/analytics/leaderboard',
            '/api/analytics/sweetspot'
        ]
        
        for endpoint in endpoints:
            response = self.client.get(endpoint)
            # Should redirect to login (302) or return unauthorized (401)
            self.assertIn(response.status_code, [302, 401])


if __name__ == '__main__':
    unittest.main()
