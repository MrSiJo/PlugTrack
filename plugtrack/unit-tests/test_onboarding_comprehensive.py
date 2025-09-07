#!/usr/bin/env python3
"""
Comprehensive Onboarding Tests for PlugTrack B7-5
Tests first-run detection, user creation, and onboarding flow.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call
from datetime import date

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from services.onboarding import OnboardingService
from models.user import User, db
from models.car import Car


class TestOnboardingComprehensive(unittest.TestCase):
    """Comprehensive tests for onboarding functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
        
        # Mock database operations
        self.user_query_patcher = patch('models.user.User.query')
        self.car_query_patcher = patch('models.car.Car.query')
        self.db_session_patcher = patch('models.user.db.session')
        
        self.mock_user_query = self.user_query_patcher.start()
        self.mock_car_query = self.car_query_patcher.start()
        self.mock_db_session = self.db_session_patcher.start()
        
        # Mock user and car objects
        self.mock_user = User(id=1, username='testuser')
        self.mock_car = Car(id=1, user_id=1, make='Tesla', model='Model 3', battery_kwh=75.0)
    
    def tearDown(self):
        """Clean up after tests."""
        self.user_query_patcher.stop()
        self.car_query_patcher.stop()
        self.db_session_patcher.stop()
    
    def test_is_first_run_no_users(self):
        """Test first run detection when no users exist."""
        with self.app_context:
            self.mock_user_query.count.return_value = 0
            
            result = OnboardingService.is_first_run()
            
            self.assertTrue(result)
            self.mock_user_query.count.assert_called_once()
    
    def test_is_first_run_with_users(self):
        """Test first run detection when users exist."""
        with self.app_context:
            self.mock_user_query.count.return_value = 1
            
            result = OnboardingService.is_first_run()
            
            self.assertFalse(result)
            self.mock_user_query.count.assert_called_once()
    
    def test_is_first_run_database_error(self):
        """Test first run detection with database error (assumes first run)."""
        with self.app_context:
            self.mock_user_query.count.side_effect = Exception("Database error")
            
            result = OnboardingService.is_first_run()
            
            self.assertTrue(result)  # Should assume first run on error
            self.app.logger.warning.assert_called_once()
    
    def test_create_initial_user_success(self):
        """Test successful initial user creation."""
        with self.app_context:
            # Mock user creation
            self.mock_user_query.filter_by.return_value.first.return_value = None  # No existing user
            self.mock_db_session.add = MagicMock()
            self.mock_db_session.commit = MagicMock()
            
            # Mock User constructor and set_password
            with patch('models.user.User') as mock_user_class:
                mock_user_instance = MagicMock()
                mock_user_instance.username = 'newuser'
                mock_user_class.return_value = mock_user_instance
                
                result = OnboardingService.create_initial_user('newuser', 'password123')
                
                self.assertTrue(result['success'])
                self.assertEqual(result['user_id'], mock_user_instance.id)
                self.mock_db_session.add.assert_called_once_with(mock_user_instance)
                self.mock_db_session.commit.assert_called_once()
                mock_user_instance.set_password.assert_called_once_with('password123')
    
    def test_create_initial_user_username_exists(self):
        """Test user creation when username already exists."""
        with self.app_context:
            # Mock existing user
            self.mock_user_query.filter_by.return_value.first.return_value = self.mock_user
            
            result = OnboardingService.create_initial_user('existinguser', 'password123')
            
            self.assertFalse(result['success'])
            self.assertIn('already exists', result['error'])
    
    def test_create_initial_user_database_error(self):
        """Test user creation with database error."""
        with self.app_context:
            self.mock_user_query.filter_by.return_value.first.return_value = None
            self.mock_db_session.add.side_effect = Exception("Database error")
            
            result = OnboardingService.create_initial_user('newuser', 'password123')
            
            self.assertFalse(result['success'])
            self.assertIn('Database error', result['error'])
    
    def test_optionally_create_first_car_success(self):
        """Test successful optional car creation."""
        with self.app_context:
            self.mock_car_query.filter_by.return_value.first.return_value = None  # No existing car
            self.mock_db_session.add = MagicMock()
            self.mock_db_session.commit = MagicMock()
            
            with patch('models.car.Car') as mock_car_class:
                mock_car_instance = MagicMock()
                mock_car_instance.id = 1
                mock_car_class.return_value = mock_car_instance
                
                result = OnboardingService.optionally_create_first_car(
                    user_id=1, make='Tesla', model='Model 3', 
                    battery_kwh=75.0, efficiency_mpkwh=4.2
                )
                
                self.assertTrue(result['success'])
                self.assertEqual(result['car_id'], 1)
                self.mock_db_session.add.assert_called_once_with(mock_car_instance)
                self.mock_db_session.commit.assert_called_once()
    
    def test_optionally_create_first_car_already_exists(self):
        """Test car creation when car already exists."""
        with self.app_context:
            self.mock_car_query.filter_by.return_value.first.return_value = self.mock_car
            
            result = OnboardingService.optionally_create_first_car(
                user_id=1, make='Tesla', model='Model 3'
            )
            
            self.assertFalse(result['success'])
            self.assertIn('already exists', result['error'])
    
    def test_optionally_create_first_car_no_data(self):
        """Test car creation with no car data provided."""
        with self.app_context:
            result = OnboardingService.optionally_create_first_car(
                user_id=1, make=None, model=None
            )
            
            self.assertTrue(result['success'])
            self.assertIn('skipped', result['message'])
            self.mock_db_session.add.assert_not_called()
    
    def test_get_onboarding_status(self):
        """Test onboarding status retrieval."""
        with self.app_context:
            self.mock_user_query.count.return_value = 0
            self.mock_car_query.count.return_value = 0
            
            status = OnboardingService.get_onboarding_status()
            
            self.assertEqual(status['user_count'], 0)
            self.assertEqual(status['car_count'], 0)
            self.assertTrue(status['is_first_run'])
    
    def test_get_onboarding_status_with_data(self):
        """Test onboarding status with existing data."""
        with self.app_context:
            self.mock_user_query.count.return_value = 1
            self.mock_car_query.count.return_value = 2
            
            status = OnboardingService.get_onboarding_status()
            
            self.assertEqual(status['user_count'], 1)
            self.assertEqual(status['car_count'], 2)
            self.assertFalse(status['is_first_run'])


class TestOnboardingRoutes(unittest.TestCase):
    """Test onboarding routes and guards."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
    
    @patch('routes.onboarding.OnboardingService.is_first_run')
    def test_onboarding_guard_first_run(self, mock_is_first_run):
        """Test onboarding guard allows access during first run."""
        from routes.onboarding import onboarding_guard
        
        mock_is_first_run.return_value = True
        
        with self.app_context:
            # Should not redirect during first run
            result = onboarding_guard()
            self.assertIsNone(result)
    
    @patch('routes.onboarding.OnboardingService.is_first_run')
    @patch('routes.onboarding.redirect')
    def test_onboarding_guard_not_first_run(self, mock_redirect, mock_is_first_run):
        """Test onboarding guard redirects when not first run."""
        from routes.onboarding import onboarding_guard
        
        mock_is_first_run.return_value = False
        mock_redirect.return_value = "redirect_response"
        
        with self.app_context:
            result = onboarding_guard()
            self.assertEqual(result, "redirect_response")
            mock_redirect.assert_called_once()
    
    @patch('routes.onboarding.OnboardingService.is_first_run')
    @patch('routes.onboarding.current_user')
    def test_onboarding_guard_authenticated_user(self, mock_current_user, mock_is_first_run):
        """Test onboarding guard redirects authenticated users."""
        from routes.onboarding import onboarding_guard
        from flask_login import AnonymousUserMixin
        
        mock_current_user.is_authenticated = True
        mock_is_first_run.return_value = True
        
        with self.app_context:
            with patch('routes.onboarding.redirect') as mock_redirect:
                mock_redirect.return_value = "redirect_response"
                result = onboarding_guard()
                self.assertEqual(result, "redirect_response")


if __name__ == '__main__':
    print("Running comprehensive onboarding tests...")
    unittest.main()
