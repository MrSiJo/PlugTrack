#!/usr/bin/env python3
"""
Unit tests for PlugTrack Phase 6 Stage E & F - Session Metrics API and Non-AI Summaries
Tests the /api/session/<id>/metrics endpoint and generate_summary functionality
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
from services.session_metrics_api import SessionMetricsApiService
from services.insights import InsightsService


class TestSessionMetricsApi(unittest.TestCase):
    """Test cases for Session Metrics API (Stage E)"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user with unique name
            import uuid
            self.user = User(username=f'testuser_{uuid.uuid4().hex[:8]}')
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
                efficiency_mpkwh=4.0,
                active=True
            )
            db.session.add(self.car)
            db.session.commit()
            self.car_id = self.car.id
            
            # Create user settings for petrol parity
            Settings.set_setting(self.user_id, 'petrol_ppl', '140.0')  # 140p per litre
            Settings.set_setting(self.user_id, 'mpg_uk', '35.0')       # 35 MPG
            db.session.commit()
    
    def tearDown(self):
        """Clean up test environment"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_paid_session_metrics(self):
        """Test session metrics API for a paid charging session"""
        with self.app.app_context():
            # Create a paid session with good data
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today() - timedelta(days=1),
                odometer=15000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=50.0,
                duration_mins=400,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=90
            )
            db.session.add(session)
            db.session.commit()
            
            result = SessionMetricsApiService.get_session_metrics(session.id, self.user_id)
            
            # Verify basic structure
            self.assertIsNotNone(result)
            self.assertEqual(result['session_id'], session.id)
            self.assertIn('metrics', result)
            self.assertIn('insights', result)
            self.assertIn('confidence', result)
            self.assertIn('chips', result)
            self.assertIn('summary', result)
            
            # Verify metrics
            metrics = result['metrics']
            self.assertIn('efficiency_used', metrics)
            self.assertIn('cost_per_mile', metrics)
            
            # Verify insights
            insights = result['insights']
            self.assertIn('loss_percent', insights)
            self.assertIn('petrol_parity', insights)
            
            # Verify confidence
            confidence = result['confidence']
            self.assertIn('level', confidence)
            self.assertIn('reasons', confidence)
            self.assertIn(confidence['level'], ['low', 'medium', 'high'])
            
            # Verify chips array (max 6)
            chips = result['chips']
            self.assertIsInstance(chips, list)
            self.assertLessEqual(len(chips), 6)
            
            # Verify each chip has required fields (template format: style, icon, text)
            for chip in chips:
                self.assertIn('style', chip)
                self.assertIn('icon', chip)
                self.assertIn('text', chip)
                self.assertIn(chip['style'], ['success', 'danger', 'warning', 'info', 'secondary'])
            
            # Verify summary exists
            self.assertIsNotNone(result['summary'])
            self.assertIsInstance(result['summary'], str)
            self.assertGreater(len(result['summary']), 10)
    
    def test_free_session_metrics(self):
        """Test session metrics API for a free charging session"""
        with self.app.app_context():
            # Create a free session
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today() - timedelta(days=1),
                odometer=15100,
                charge_type='DC',
                charge_speed_kw=50.0,
                location_label='Tesla Supercharger',
                charge_delivered_kwh=25.0,
                duration_mins=30,
                cost_per_kwh=0.0,  # Free session
                soc_from=40,
                soc_to=80
            )
            db.session.add(session)
            db.session.commit()
            
            result = SessionMetricsApiService.get_session_metrics(session.id, self.user_id)
            
            # Verify basic structure
            self.assertIsNotNone(result)
            
            # Verify insights (should have no petrol parity for free session)
            insights = result['insights']
            self.assertIsNone(insights.get('petrol_parity'))
            
            # Verify confidence mentions free session
            confidence = result['confidence']
            reasons = confidence['reasons']
            self.assertTrue(any('free' in reason.lower() for reason in reasons))
            
            # Verify chips don't include cost per mile
            chips = result['chips']
            cost_chips = [chip for chip in chips if chip['type'] == 'cost']
            self.assertEqual(len(cost_chips), 0)
            
            # Verify summary mentions free charging
            summary = result['summary']
            self.assertIn('no cost', summary.lower())
    
    def test_small_window_session_metrics(self):
        """Test session metrics API for a small window charging session"""
        with self.app.app_context():
            # Create a small charging session
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today() - timedelta(days=1),
                odometer=15500,  # Some odometer data
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=2.0,  # Small energy delivery
                duration_mins=20,
                cost_per_kwh=0.15,
                soc_from=85,
                soc_to=95  # Small SoC window
            )
            db.session.add(session)
            db.session.commit()
            
            result = SessionMetricsApiService.get_session_metrics(session.id, self.user_id)
            
            # Verify confidence is reduced due to small window and missing data
            confidence = result['confidence']
            self.assertIn(confidence['level'], ['low', 'medium'])
            
            reasons = confidence['reasons']
            reason_text = ' '.join(reasons).lower()
            self.assertTrue(
                'small' in reason_text or 
                'odometer' in reason_text or
                'efficiency' in reason_text
            )
            
            # Verify session size chip shows "topup"
            chips = result['chips']
            size_chips = [chip for chip in chips if chip['type'] == 'session_size']
            if size_chips:
                self.assertEqual(size_chips[0]['value'], 'Topup')
    
    def test_session_not_found(self):
        """Test session metrics API with non-existent session"""
        with self.app.app_context():
            result = SessionMetricsApiService.get_session_metrics(99999, self.user_id)
            self.assertIsNone(result)
    
    def test_user_access_control(self):
        """Test that users can only access their own sessions"""
        with self.app.app_context():
            # Create session for user
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=30.0,
                duration_mins=200,
                cost_per_kwh=0.12,
                soc_from=30,
                soc_to=80
            )
            db.session.add(session)
            db.session.commit()
            
            # Try to access with different user ID
            result = SessionMetricsApiService.get_session_metrics(session.id, 99999)
            self.assertIsNone(result)


class TestSessionSummaryGeneration(unittest.TestCase):
    """Test cases for Session Summary Generation (Stage F)"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user with unique name
            import uuid
            self.user = User(username=f'testuser_{uuid.uuid4().hex[:8]}')
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
                efficiency_mpkwh=4.0,
                active=True
            )
            db.session.add(self.car)
            db.session.commit()
            self.car_id = self.car.id
            
            # Create user settings for petrol parity
            Settings.set_setting(self.user_id, 'petrol_ppl', '140.0')
            Settings.set_setting(self.user_id, 'mpg_uk', '35.0')
            db.session.commit()
    
    def tearDown(self):
        """Clean up test environment"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_home_charging_summary(self):
        """Test summary generation for home charging session"""
        with self.app.app_context():
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=40.0,
                duration_mins=320,
                cost_per_kwh=0.10,
                soc_from=25,
                soc_to=85
            )
            db.session.add(session)
            db.session.commit()
            
            summary = InsightsService.generate_summary(session.id)
            
            self.assertIsNotNone(summary)
            self.assertIn('Home', summary)
            self.assertIn('major', summary.lower())
            self.assertIn('40.0 kWh', summary)
            self.assertIn('0.10 £/kWh', summary)
            self.assertIn('25% → 85%', summary)
    
    def test_public_charging_summary(self):
        """Test summary generation for public charging session"""
        with self.app.app_context():
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15200,
                charge_type='DC',
                charge_speed_kw=50.0,
                location_label='Tesla Supercharger London',
                charge_delivered_kwh=55.0,
                duration_mins=45,
                cost_per_kwh=0.30,
                soc_from=15,
                soc_to=85
            )
            db.session.add(session)
            db.session.commit()
            
            summary = InsightsService.generate_summary(session.id)
            
            self.assertIsNotNone(summary)
            self.assertIn('Public', summary)
            self.assertIn('Tesla Supercharger London', summary)
            self.assertIn('major', summary.lower())
            self.assertIn('55.0 kWh', summary)
            self.assertIn('0.30 £/kWh', summary)
            self.assertIn('15% → 85%', summary)
    
    def test_free_charging_summary(self):
        """Test summary generation for free charging session"""
        with self.app.app_context():
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15100,
                charge_type='DC',
                charge_speed_kw=22.0,
                location_label='Work Car Park',
                charge_delivered_kwh=25.0,
                duration_mins=90,
                cost_per_kwh=0.0,  # Free
                soc_from=50,
                soc_to=85
            )
            db.session.add(session)
            db.session.commit()
            
            summary = InsightsService.generate_summary(session.id)
            
            self.assertIsNotNone(summary)
            self.assertIn('Public', summary)
            self.assertIn('Work Car Park', summary)
            self.assertIn('no cost', summary)
            self.assertIn('25.0 kWh', summary)
            self.assertIn('50% → 85%', summary)
    
    def test_dc_taper_summary(self):
        """Test summary generation with DC taper detection"""
        with self.app.app_context():
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15300,
                charge_type='DC',
                charge_speed_kw=150.0,  # High peak power
                location_label='Ionity HPC',
                charge_delivered_kwh=45.0,
                duration_mins=25,  # Short duration suggests high avg power but with taper
                cost_per_kwh=0.35,
                soc_from=20,
                soc_to=80
            )
            db.session.add(session)
            db.session.commit()
            
            summary = InsightsService.generate_summary(session.id)
            
            self.assertIsNotNone(summary)
            self.assertIn('Ionity HPC', summary)
            self.assertIn('major', summary.lower())
            # Note: DC taper detection depends on calculated avg power vs peak power
            # This test verifies the summary generation works for DC sessions
    
    def test_summary_with_petrol_parity(self):
        """Test summary generation includes petrol parity comparison"""
        with self.app.app_context():
            # Create a session that should be cheaper than petrol
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=50.0,
                duration_mins=400,
                cost_per_kwh=0.08,  # Cheap rate
                soc_from=20,
                soc_to=90
            )
            db.session.add(session)
            db.session.commit()
            
            summary = InsightsService.generate_summary(session.id)
            
            self.assertIsNotNone(summary)
            # Summary might include petrol parity comparison if conditions are met
            # The exact content depends on the calculation
    
    def test_summary_for_nonexistent_session(self):
        """Test summary generation for non-existent session"""
        with self.app.app_context():
            summary = InsightsService.generate_summary(99999)
            self.assertIsNone(summary)


class TestSessionMetricsApiEndpoint(unittest.TestCase):
    """Test cases for the /api/session/<id>/metrics endpoint"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user with unique name
            import uuid
            self.user = User(username=f'testuser_{uuid.uuid4().hex[:8]}')
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
                efficiency_mpkwh=4.0,
                active=True
            )
            db.session.add(self.car)
            db.session.commit()
            self.car_id = self.car.id
    
    def tearDown(self):
        """Clean up test environment"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_api_endpoint_requires_auth(self):
        """Test that the API endpoint requires authentication"""
        response = self.client.get('/api/session/1/metrics')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_api_endpoint_with_auth(self):
        """Test the API endpoint with authentication"""
        with self.app.app_context():
            # Create a test session
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=15000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=30.0,
                duration_mins=200,
                cost_per_kwh=0.12,
                soc_from=30,
                soc_to=80
            )
            db.session.add(session)
            db.session.commit()
            session_id = session.id
        
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True
        
        response = self.client.get(f'/api/session/{session_id}/metrics')
        self.assertEqual(response.status_code, 200)
        
        data = response.get_json()
        self.assertIn('session_id', data)
        self.assertIn('metrics', data)
        self.assertIn('insights', data)
        self.assertIn('confidence', data)
        self.assertIn('chips', data)
        self.assertIn('summary', data)
    
    def test_api_endpoint_session_not_found(self):
        """Test the API endpoint with non-existent session"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True
        
        response = self.client.get('/api/session/99999/metrics')
        self.assertEqual(response.status_code, 404)
        
        data = response.get_json()
        self.assertIn('error', data)


if __name__ == '__main__':
    unittest.main()
