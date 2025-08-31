"""
Unit tests for Dashboard P6-4 enhancements
Tests the lifetime totals and cost extremes functionality.
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


class TestDashboardP6_4(unittest.TestCase):
    """Test P6-4 dashboard enhancements"""
    
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
    
    def test_analytics_summary_with_sessions(self):
        """Test analytics summary calculation with charging sessions"""
        with self.app.app_context():
            # Create test sessions with varying costs
            sessions = [
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=10),
                    charge_delivered_kwh=50.0,
                    cost_per_kwh=0.20,  # Cheap session
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
                    charge_delivered_kwh=30.0,
                    cost_per_kwh=0.50,  # Expensive session
                    location_label='Rapid Charger',
                    charge_type='DC',
                    soc_from=30,
                    soc_to=80,
                    odometer=10200
                ),
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=1),
                    charge_delivered_kwh=25.0,
                    cost_per_kwh=0.30,  # Medium cost session
                    location_label='Public AC',
                    charge_type='AC',
                    soc_from=40,
                    soc_to=90,
                    odometer=10350
                )
            ]
            
            for session in sessions:
                db.session.add(session)
            db.session.commit()
            
            # Test analytics summary
            summary = AnalyticsAggService.get_analytics_summary(self.user.id)
            
            # Check lifetime totals
            self.assertIsNotNone(summary['lifetime'])
            self.assertEqual(summary['lifetime']['kwh'], 105.0)  # 50 + 30 + 25
            self.assertEqual(summary['lifetime']['cost'], 40.0)  # (50*0.20) + (30*0.50) + (25*0.30)
            
            # Check weighted efficiency is calculated
            self.assertIsNotNone(summary['weighted_efficiency'])
            self.assertGreater(summary['weighted_efficiency'], 0)
            
            # Check cost extremes
            self.assertIsNotNone(summary['cheapest'])
            self.assertIsNotNone(summary['most_expensive'])
            
            # Cheapest should be the home charging session (0.20 p/kWh)
            self.assertEqual(summary['cheapest']['location'], 'Home')
            self.assertEqual(summary['cheapest']['cost_per_kwh'], 0.20)
            
            # Most expensive should be the rapid charger session (0.50 p/kWh)
            self.assertEqual(summary['most_expensive']['location'], 'Rapid Charger')
            self.assertEqual(summary['most_expensive']['cost_per_kwh'], 0.50)
    
    def test_dashboard_route_includes_analytics_summary(self):
        """Test that dashboard route includes analytics summary data"""
        with self.app.app_context():
            # Create a test session
            session = ChargingSession(
                user_id=self.user.id,
                car_id=self.car.id,
                date=date.today(),
                charge_delivered_kwh=40.0,
                cost_per_kwh=0.25,
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
            
            # Test dashboard page
            response = self.client.get('/')
            self.assertEqual(response.status_code, 200)
            
            content = response.data.decode('utf-8')
            
            # Check for lifetime totals section
            self.assertIn('Lifetime Totals', content)
            self.assertIn('All-time cumulative data', content)
            
            # Check for cost extremes sections
            # Note: With only one session, both cheapest and most expensive will be the same
            self.assertIn('Cheapest Session', content)
            self.assertIn('Most Expensive Session', content)
    
    def test_analytics_summary_no_sessions(self):
        """Test analytics summary with no charging sessions"""
        with self.app.app_context():
            summary = AnalyticsAggService.get_analytics_summary(self.user.id)
            
            # Check default values for no sessions
            self.assertEqual(summary['weighted_efficiency'], 0)
            self.assertEqual(summary['lifetime']['kwh'], 0)
            self.assertEqual(summary['lifetime']['miles'], 0)
            self.assertEqual(summary['lifetime']['cost'], 0)
            self.assertEqual(summary['lifetime']['saved_vs_petrol'], 0)
            self.assertIsNone(summary['cheapest'])
            self.assertIsNone(summary['most_expensive'])
    
    def test_dashboard_weighted_efficiency_label_fix(self):
        """Test that weighted efficiency widget uses single line label"""
        with self.app.app_context():
            # Mock login
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.user.id)
                sess['_fresh'] = True
            
            # Test dashboard page
            response = self.client.get('/')
            self.assertEqual(response.status_code, 200)
            
            content = response.data.decode('utf-8')
            
            # Check that the label is just "Weighted Efficiency" without subtitle
            self.assertIn('Weighted Efficiency</p>', content)
            
            # Check that the long subtitle is NOT present
            self.assertNotIn('kWh-weighted mi/kWh', content)
    
    def test_cost_extremes_with_multiple_sessions(self):
        """Test cost extremes identification with multiple sessions"""
        with self.app.app_context():
            # Create sessions with clearly different costs per mile
            sessions = [
                # Cheap home session
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=5),
                    charge_delivered_kwh=40.0,
                    cost_per_kwh=0.10,  # Very cheap
                    location_label='Home Solar',
                    charge_type='AC',
                    soc_from=20,
                    soc_to=80,
                    odometer=10000
                ),
                # Expensive rapid session
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=3),
                    charge_delivered_kwh=25.0,
                    cost_per_kwh=0.80,  # Very expensive
                    location_label='Motorway Services',
                    charge_type='DC',
                    soc_from=10,
                    soc_to=80,
                    odometer=10100
                ),
                # Medium cost session
                ChargingSession(
                    user_id=self.user.id,
                    car_id=self.car.id,
                    date=date.today() - timedelta(days=1),
                    charge_delivered_kwh=30.0,
                    cost_per_kwh=0.35,  # Medium cost
                    location_label='Public Charger',
                    charge_type='AC',
                    soc_from=30,
                    soc_to=85,
                    odometer=10250
                )
            ]
            
            for session in sessions:
                db.session.add(session)
            db.session.commit()
            
            summary = AnalyticsAggService.get_analytics_summary(self.user.id)
            
            # Check that cheapest and most expensive are correctly identified
            self.assertIsNotNone(summary['cheapest'])
            self.assertIsNotNone(summary['most_expensive'])
            
            # Cheapest should be home solar
            self.assertEqual(summary['cheapest']['location'], 'Home Solar')
            self.assertEqual(summary['cheapest']['cost_per_kwh'], 0.10)
            
            # Most expensive should be motorway services
            self.assertEqual(summary['most_expensive']['location'], 'Motorway Services')
            self.assertEqual(summary['most_expensive']['cost_per_kwh'], 0.80)
            
            # They should be different sessions
            self.assertNotEqual(summary['cheapest']['session_id'], summary['most_expensive']['session_id'])


if __name__ == '__main__':
    unittest.main()
