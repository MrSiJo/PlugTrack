#!/usr/bin/env python3
"""
Unit tests for PlugTrack Phase 6 Stage D - Reminders API
Tests the /api/reminders endpoint and RemindersApiService
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
from services.reminders_api import RemindersApiService


class TestRemindersApi(unittest.TestCase):
    """Test cases for Reminders API"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.user = User(username='testuser')
            self.user.set_password('testpass')
            db.session.add(self.user)
            db.session.commit()
            
            # Store user ID for later use
            self.user_id = self.user.id
            
            # Create test car with reminder settings
            self.car = Car(
                user_id=self.user_id,
                make='Tesla',
                model='Model 3',
                battery_kwh=75.0,
                efficiency_mpkwh=4.0,
                active=True,
                recommended_full_charge_enabled=True,
                recommended_full_charge_frequency_value=7,
                recommended_full_charge_frequency_unit='days'
            )
            db.session.add(self.car)
            db.session.commit()
            
            # Store car ID for later use
            self.car_id = self.car.id
            
            # Create test car without reminder settings
            self.car_no_reminders = Car(
                user_id=self.user_id,
                make='Nissan',
                model='Leaf',
                battery_kwh=40.0,
                efficiency_mpkwh=3.5,
                active=True,
                recommended_full_charge_enabled=False
            )
            db.session.add(self.car_no_reminders)
            db.session.commit()
            
            # Store car ID for later use
            self.car_no_reminders_id = self.car_no_reminders.id
    
    def tearDown(self):
        """Clean up test environment"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_no_reminders_due_or_upcoming(self):
        """Test API response when no reminders are due or upcoming"""
        with self.app.app_context():
            # Disable reminders for the test car to get no reminders
            car = Car.query.get(self.car_id)
            car.recommended_full_charge_enabled = False
            db.session.commit()
            
            # No charging sessions exist yet, and no cars have reminders enabled
            result = RemindersApiService.get_reminders_api(self.user_id)
            
            self.assertEqual(result['due'], [])
            self.assertEqual(result['upcoming'], [])
    
    def test_reminder_due_overdue(self):
        """Test API response when a reminder is overdue"""
        with self.app.app_context():
            # Create an old high charge session (10 days ago, should be overdue)
            old_date = date.today() - timedelta(days=10)
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=old_date,
                odometer=1000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=50.0,
                duration_mins=400,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=100  # This is a full charge
            )
            db.session.add(session)
            db.session.commit()
            
            result = RemindersApiService.get_reminders_api(self.user_id)
            
            # Should have one due reminder
            self.assertEqual(len(result['due']), 1)
            self.assertEqual(len(result['upcoming']), 0)
            
            due_reminder = result['due'][0]
            self.assertEqual(due_reminder['car_id'], self.car_id)
            self.assertEqual(due_reminder['car_name'], 'Tesla Model 3')
            self.assertEqual(due_reminder['last_full_date'], old_date.isoformat())
            self.assertGreater(due_reminder['overdue_days'], 0)
    
    def test_reminder_upcoming(self):
        """Test API response when a reminder is upcoming but not due"""
        with self.app.app_context():
            # Create a recent high charge session (3 days ago, should be upcoming)
            recent_date = date.today() - timedelta(days=3)
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=recent_date,
                odometer=1000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=50.0,
                duration_mins=400,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=95  # This counts as a full charge (≥95%)
            )
            db.session.add(session)
            db.session.commit()
            
            result = RemindersApiService.get_reminders_api(self.user_id)
            
            # Should have one upcoming reminder
            self.assertEqual(len(result['due']), 0)
            self.assertEqual(len(result['upcoming']), 1)
            
            upcoming_reminder = result['upcoming'][0]
            self.assertEqual(upcoming_reminder['car_id'], self.car_id)
            self.assertEqual(upcoming_reminder['car_name'], 'Tesla Model 3')
            self.assertEqual(upcoming_reminder['last_full_date'], recent_date.isoformat())
            self.assertIn('due_in_days', upcoming_reminder)
            self.assertGreater(upcoming_reminder['due_in_days'], 0)
    
    def test_car_id_filter(self):
        """Test API response with car_id filter"""
        with self.app.app_context():
            # Create overdue reminder for one car
            old_date = date.today() - timedelta(days=10)
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=old_date,
                odometer=1000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=50.0,
                duration_mins=400,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=100
            )
            db.session.add(session)
            db.session.commit()
            
            # Test filtering by specific car
            result = RemindersApiService.get_reminders_api(self.user_id, car_id=self.car_id)
            self.assertEqual(len(result['due']), 1)
            
            # Test filtering by different car
            result = RemindersApiService.get_reminders_api(self.user_id, car_id=self.car_no_reminders_id)
            self.assertEqual(len(result['due']), 0)
    
    def test_date_range_filter(self):
        """Test API response with date range filters"""
        with self.app.app_context():
            # Create upcoming reminder
            recent_date = date.today() - timedelta(days=3)
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=recent_date,
                odometer=1000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=50.0,
                duration_mins=400,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=95
            )
            db.session.add(session)
            db.session.commit()
            
            # Test with date range that includes the upcoming reminder
            future_date = date.today() + timedelta(days=10)
            result = RemindersApiService.get_reminders_api(
                self.user_id, date_to=future_date
            )
            self.assertEqual(len(result['upcoming']), 1)
            
            # Test with date range that excludes the upcoming reminder
            near_future = date.today() + timedelta(days=2)
            result = RemindersApiService.get_reminders_api(
                self.user_id, date_to=near_future
            )
            self.assertEqual(len(result['upcoming']), 0)
    
    def test_car_without_reminder_settings(self):
        """Test that cars without reminder settings don't appear in results"""
        with self.app.app_context():
            # Disable reminders for the main test car
            car = Car.query.get(self.car_id)
            car.recommended_full_charge_enabled = False
            db.session.commit()
            
            # Create session for car without reminder settings
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_no_reminders_id,
                date=date.today() - timedelta(days=30),
                odometer=1000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=30.0,
                duration_mins=300,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=100
            )
            db.session.add(session)
            db.session.commit()
            
            result = RemindersApiService.get_reminders_api(self.user_id)
            
            # Should have no reminders since no cars have reminder settings enabled
            self.assertEqual(len(result['due']), 0)
            self.assertEqual(len(result['upcoming']), 0)
    
    def test_monthly_frequency_calculation(self):
        """Test reminder calculation for monthly frequency"""
        with self.app.app_context():
            # Update car to have monthly frequency
            car = Car.query.get(self.car_id)
            car.recommended_full_charge_frequency_value = 1
            car.recommended_full_charge_frequency_unit = 'months'
            db.session.commit()
            
            # Create session 35 days ago (should be overdue for monthly)
            old_date = date.today() - timedelta(days=35)
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=old_date,
                odometer=1000,
                charge_type='AC',
                charge_speed_kw=7.0,
                location_label='Home',
                charge_delivered_kwh=50.0,
                duration_mins=400,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=100
            )
            db.session.add(session)
            db.session.commit()
            
            result = RemindersApiService.get_reminders_api(self.user_id)
            
            # Should have one due reminder
            self.assertEqual(len(result['due']), 1)
            due_reminder = result['due'][0]
            self.assertGreater(due_reminder['overdue_days'], 0)


class TestRemindersApiEndpoint(unittest.TestCase):
    """Test cases for the /api/reminders endpoint"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.user = User(username='testuser')
            self.user.set_password('testpass')
            db.session.add(self.user)
            db.session.commit()
            
            # Store user ID for later use
            self.user_id = self.user.id
    
    def tearDown(self):
        """Clean up test environment"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_api_endpoint_requires_auth(self):
        """Test that the API endpoint requires authentication"""
        response = self.client.get('/api/reminders')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_api_endpoint_with_auth(self):
        """Test the API endpoint with authentication"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True
        
        response = self.client.get('/api/reminders')
        self.assertEqual(response.status_code, 200)
        
        data = response.get_json()
        self.assertIn('due', data)
        self.assertIn('upcoming', data)
        self.assertIsInstance(data['due'], list)
        self.assertIsInstance(data['upcoming'], list)
    
    def test_api_endpoint_with_filters(self):
        """Test the API endpoint with query parameters"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True
        
        # Test with car_id filter
        response = self.client.get('/api/reminders?car_id=1')
        self.assertEqual(response.status_code, 200)
        
        # Test with date filters
        response = self.client.get('/api/reminders?date_from=2024-01-01&date_to=2024-12-31')
        self.assertEqual(response.status_code, 200)
        
        # Test with invalid date format (should not crash)
        response = self.client.get('/api/reminders?date_from=invalid-date')
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
