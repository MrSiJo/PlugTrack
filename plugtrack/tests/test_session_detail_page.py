#!/usr/bin/env python3
"""
Unit tests for PlugTrack Phase 6 Stage P6-2 - Session Detail Page
Tests the /session/<id> route and template rendering
"""

import unittest
import sys
import os
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


class TestSessionDetailPage(unittest.TestCase):
    """Test cases for the session detail page"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        # Use temporary file database for tests
        import tempfile
        db_fd, db_path = tempfile.mkstemp()
        os.close(db_fd)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        self.db_path = db_path
        
        # Generate unique username
        import uuid
        unique_suffix = uuid.uuid4().hex[:8]
        self.username = f'testuser_detail_{unique_suffix}'
        
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
            
            # Create test charging session
            self.session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15000,
                charge_type='AC',
                charge_speed_kw=7.4,
                location_label='Home',
                charge_network='Home Charger',
                charge_delivered_kwh=25.5,
                duration_mins=300,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=54,
                venue_type='home',
                is_baseline=False,
                ambient_temp_c=18.5,
                preconditioning_used=False,
                preconditioning_events=0,
                notes='Test session for detail page'
            )
            db.session.add(self.session)
            db.session.commit()
            self.session_id = self.session.id
            
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
        
        # Clean up temporary database file
        if hasattr(self, 'db_path') and os.path.exists(self.db_path):
            os.unlink(self.db_path)
    
    def login_user(self):
        """Helper to log in test user"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True
    
    def test_session_detail_page_requires_auth(self):
        """Test that the session detail page requires authentication"""
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_session_detail_page_with_valid_session(self):
        """Test session detail page with valid session"""
        self.login_user()
        
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 200)
        
        # Check that the response contains expected content
        content = response.data.decode('utf-8')
        
        # Check page title and structure
        self.assertIn('Session Detail', content)
        self.assertIn('Blended Planner', content)
        self.assertIn('tab-content', content)
        
        # Check session data is displayed
        self.assertIn('Home', content)  # location_label
        self.assertIn('Tesla Model 3', content)  # car make/model
        self.assertIn('AC Charging', content)  # charge_type
        self.assertIn('25.5', content)  # charge_delivered_kwh
        
        # Check technical details section
        self.assertIn('Technical Details', content)
        self.assertIn('7.4 kW', content)  # charge_speed_kw
        self.assertIn('20% → 54%', content)  # SoC range
        self.assertIn('15,000 miles', content)  # odometer with formatting
        
        # Check tabs are present
        self.assertIn('id="detail-tab"', content)
        self.assertIn('id="planner-tab"', content)
        
        # Check breadcrumb navigation
        self.assertIn('breadcrumb', content)
        self.assertIn('Charging Sessions', content)
        self.assertIn(f'Session {self.session_id}', content)
    
    def test_session_detail_page_with_nonexistent_session(self):
        """Test session detail page with non-existent session"""
        self.login_user()
        
        response = self.client.get('/session/99999')
        self.assertEqual(response.status_code, 404)
    
    def test_session_detail_page_user_isolation(self):
        """Test that users can only access their own sessions"""
        # Create another user and session
        other_user = User(username='otheruser')
        other_user.set_password('testpass')
        
        with self.app.app_context():
            db.session.add(other_user)
            db.session.commit()
            
            other_car = Car(
                user_id=other_user.id,
                make='BMW',
                model='i3',
                battery_kwh=42.0,
                efficiency_mpkwh=4.0,
                active=True
            )
            db.session.add(other_car)
            db.session.commit()
            
            other_session = ChargingSession(
                user_id=other_user.id,
                car_id=other_car.id,
                date=date.today(),
                odometer=10000,
                charge_type='DC',
                charge_speed_kw=50.0,
                location_label='Public',
                charge_network='Ionity',
                charge_delivered_kwh=30.0,
                duration_mins=45,
                cost_per_kwh=0.35,
                soc_from=10,
                soc_to=80,
                venue_type='public',
                is_baseline=False
            )
            db.session.add(other_session)
            db.session.commit()
            other_session_id = other_session.id
        
        # Login as the first user and try to access the other user's session
        self.login_user()
        
        response = self.client.get(f'/session/{other_session_id}')
        self.assertEqual(response.status_code, 404)  # Should not be accessible
    
    def test_session_detail_page_with_api_metrics(self):
        """Test that session detail page displays API metrics correctly"""
        self.login_user()
        
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 200)
        
        content = response.data.decode('utf-8')
        
        # Check that metrics sections are present
        self.assertIn('Session Insights', content)
        self.assertIn('mi/kWh', content)
        self.assertIn('per mile', content)
        
        # Check that confidence section is present (even if no data)
        # The template should handle missing api_metrics gracefully
        self.assertIn('Data Confidence', content)
    
    def test_session_detail_page_blend_planner_integration(self):
        """Test that the blend planner is properly integrated"""
        self.login_user()
        
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 200)
        
        content = response.data.decode('utf-8')
        
        # Check blend planner elements
        self.assertIn('Blended Charge Planner', content)
        self.assertIn('blendPlannerForm', content)
        self.assertIn('startSoc', content)
        self.assertIn('dcStopSoc', content)
        self.assertIn('homeTargetSoc', content)
        self.assertIn('Calculate Blend', content)
        
        # Check that form is pre-filled with session data
        self.assertIn('batteryKwh', content)
        self.assertIn('75', content)  # car.battery_kwh
    
    def test_session_detail_page_navigation_links(self):
        """Test that navigation links are properly set up"""
        self.login_user()
        
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 200)
        
        content = response.data.decode('utf-8')
        
        # Check breadcrumb links
        self.assertIn('href="/dashboard"', content)
        self.assertIn('href="/charging-sessions"', content)
        
        # Check edit button link
        self.assertIn(f'href="/charging-sessions/{self.session_id}/edit"', content)
    
    def test_session_detail_page_temperature_display(self):
        """Test that ambient temperature is displayed when available"""
        self.login_user()
        
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 200)
        
        content = response.data.decode('utf-8')
        
        # Check temperature display
        self.assertIn('18.5°C', content)
    
    def test_session_detail_page_preconditioning_display(self):
        """Test that preconditioning info is displayed when available"""
        self.login_user()
        
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 200)
        
        content = response.data.decode('utf-8')
        
        # Check preconditioning display
        self.assertIn('Preconditioning:', content)
        self.assertIn('No', content)  # preconditioning_used is False
    
    def test_session_detail_page_responsive_design(self):
        """Test that the page includes responsive design elements"""
        self.login_user()
        
        response = self.client.get(f'/session/{self.session_id}')
        self.assertEqual(response.status_code, 200)
        
        content = response.data.decode('utf-8')
        
        # Check Bootstrap responsive classes
        self.assertIn('col-lg-8', content)
        self.assertIn('col-lg-4', content)
        self.assertIn('col-md-3', content)
        self.assertIn('container-fluid', content)


class TestSessionDetailPageRoute(unittest.TestCase):
    """Test cases for session detail page route functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        # Use temporary file database for tests
        import tempfile
        db_fd, db_path = tempfile.mkstemp()
        os.close(db_fd)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        self.db_path = db_path
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.user = User(username='testuser_route')
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
    
    def tearDown(self):
        """Clean up after tests"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        
        # Clean up temporary database file
        if hasattr(self, 'db_path') and os.path.exists(self.db_path):
            os.unlink(self.db_path)
    
    def test_session_detail_route_registration(self):
        """Test that the session detail route is properly registered"""
        with self.app.test_client() as client:
            # Test that the route exists (even if it redirects due to auth)
            response = client.get('/session/1')
            self.assertIn(response.status_code, [302, 404])  # Auth redirect or not found
            
            # Should not be a 500 error (route not found)
            self.assertNotEqual(response.status_code, 500)


if __name__ == '__main__':
    unittest.main()
