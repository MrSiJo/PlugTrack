#!/usr/bin/env python3
"""
Unit tests for onboarding functionality
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from services.onboarding import OnboardingService
from models.user import User, db
from models.car import Car


class TestOnboardingService(unittest.TestCase):
    """Test cases for OnboardingService"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock the database session
        self.mock_db_session = MagicMock()
        self.mock_query = MagicMock()
        
        # Patch the database session
        self.db_patcher = patch('services.onboarding.db')
        self.mock_db = self.db_patcher.start()
        self.mock_db.session = self.mock_db_session
        
        # Patch the User model query
        self.user_query_patcher = patch('services.onboarding.User.query')
        self.mock_user_query = self.user_query_patcher.start()
        
        # Patch the Car model query
        self.car_query_patcher = patch('services.onboarding.Car')
        self.mock_car_class = self.car_query_patcher.start()
        
        # Patch the current_app logger
        self.logger_patcher = patch('services.onboarding.current_app')
        self.mock_app = self.logger_patcher.start()
        self.mock_app.logger = MagicMock()
    
    def tearDown(self):
        """Clean up after tests"""
        self.db_patcher.stop()
        self.user_query_patcher.stop()
        self.car_query_patcher.stop()
        self.logger_patcher.stop()
    
    def test_is_first_run_no_users(self):
        """Test is_first_run returns True when no users exist"""
        # Mock no users in database
        self.mock_user_query.count.return_value = 0
        
        result = OnboardingService.is_first_run()
        
        self.assertTrue(result)
        self.mock_user_query.count.assert_called_once()
    
    def test_is_first_run_with_users(self):
        """Test is_first_run returns False when users exist"""
        # Mock users exist in database
        self.mock_user_query.count.return_value = 1
        
        result = OnboardingService.is_first_run()
        
        self.assertFalse(result)
        self.mock_user_query.count.assert_called_once()
    
    def test_is_first_run_database_error(self):
        """Test is_first_run handles database errors gracefully"""
        # Mock database error
        self.mock_user_query.count.side_effect = Exception("Database error")
        
        result = OnboardingService.is_first_run()
        
        self.assertFalse(result)
        self.mock_app.logger.error.assert_called_once()
    
    def test_create_initial_user_success(self):
        """Test successful initial user creation"""
        # Mock first run (no users)
        self.mock_user_query.count.return_value = 0
        self.mock_user_query.filter_by.return_value.first.return_value = None
        
        # Mock user creation
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.created_at = "2024-01-01"
        
        with patch('services.onboarding.User') as mock_user_class:
            mock_user_class.return_value = mock_user
            
            result = OnboardingService.create_initial_user("testuser", "password123")
            
            self.assertTrue(result['success'])
            self.assertEqual(result['user']['username'], "testuser")
            self.assertEqual(result['user']['id'], 1)
            
            # Verify user was added to session and committed
            self.mock_db_session.add.assert_called_once_with(mock_user)
            self.mock_db_session.commit.assert_called_once()
    
    def test_create_initial_user_not_first_run(self):
        """Test create_initial_user fails when users already exist"""
        # Mock users already exist
        self.mock_user_query.count.return_value = 1
        
        result = OnboardingService.create_initial_user("testuser", "password123")
        
        self.assertFalse(result['success'])
        self.assertIn("Users already exist", result['error'])
    
    def test_create_initial_user_invalid_username(self):
        """Test create_initial_user fails with invalid username"""
        # Mock first run
        self.mock_user_query.count.return_value = 0
        
        result = OnboardingService.create_initial_user("ab", "password123")
        
        self.assertFalse(result['success'])
        self.assertIn("Username must be at least 3 characters", result['error'])
    
    def test_create_initial_user_invalid_password(self):
        """Test create_initial_user fails with invalid password"""
        # Mock first run
        self.mock_user_query.count.return_value = 0
        
        result = OnboardingService.create_initial_user("testuser", "123")
        
        self.assertFalse(result['success'])
        self.assertIn("Password must be at least 6 characters", result['error'])
    
    def test_create_initial_user_username_exists(self):
        """Test create_initial_user fails when username already exists"""
        # Mock first run but username exists
        self.mock_user_query.count.return_value = 0
        self.mock_user_query.filter_by.return_value.first.return_value = MagicMock()
        
        result = OnboardingService.create_initial_user("testuser", "password123")
        
        self.assertFalse(result['success'])
        self.assertIn("Username already exists", result['error'])
    
    def test_create_initial_user_database_error(self):
        """Test create_initial_user handles database errors"""
        # Mock first run
        self.mock_user_query.count.return_value = 0
        self.mock_user_query.filter_by.return_value.first.return_value = None
        
        # Mock database error on commit
        self.mock_db_session.commit.side_effect = Exception("Database error")
        
        result = OnboardingService.create_initial_user("testuser", "password123")
        
        self.assertFalse(result['success'])
        self.assertIn("Failed to create user", result['error'])
        self.mock_db_session.rollback.assert_called_once()
    
    def test_optionally_create_first_car_success(self):
        """Test successful car creation"""
        # Mock user exists
        mock_user = MagicMock()
        mock_user.id = 1
        self.mock_user_query.get.return_value = mock_user
        
        # Mock car creation
        mock_car = MagicMock()
        mock_car.id = 1
        mock_car.make = "Tesla"
        mock_car.model = "Model 3"
        mock_car.battery_kwh = 75.0
        mock_car.efficiency_mpkwh = 4.2
        mock_car.active = True
        
        self.mock_car_class.return_value = mock_car
        
        result = OnboardingService.optionally_create_first_car(
            user_id=1,
            battery_kwh=75.0,
            efficiency_mpkwh=4.2,
            make="Tesla",
            model="Model 3"
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['car']['make'], "Tesla")
        self.assertEqual(result['car']['model'], "Model 3")
        
        # Verify car was added to session and committed
        self.mock_db_session.add.assert_called_once_with(mock_car)
        self.mock_db_session.commit.assert_called_once()
    
    def test_optionally_create_first_car_no_data(self):
        """Test car creation with no data provided"""
        # Mock user exists
        mock_user = MagicMock()
        mock_user.id = 1
        self.mock_user_query.get.return_value = mock_user
        
        result = OnboardingService.optionally_create_first_car(user_id=1)
        
        self.assertTrue(result['success'])
        self.assertIsNone(result['car'])
        self.assertIn("No car data provided", result['message'])
    
    def test_optionally_create_first_car_user_not_found(self):
        """Test car creation fails when user doesn't exist"""
        # Mock user not found
        self.mock_user_query.get.return_value = None
        
        result = OnboardingService.optionally_create_first_car(
            user_id=999,
            battery_kwh=75.0,
            make="Tesla",
            model="Model 3"
        )
        
        self.assertFalse(result['success'])
        self.assertIn("User not found", result['error'])
    
    def test_optionally_create_first_car_invalid_battery(self):
        """Test car creation fails with invalid battery capacity"""
        # Mock user exists
        mock_user = MagicMock()
        mock_user.id = 1
        self.mock_user_query.get.return_value = mock_user
        
        result = OnboardingService.optionally_create_first_car(
            user_id=1,
            battery_kwh=0,  # Invalid
            make="Tesla",
            model="Model 3"
        )
        
        self.assertFalse(result['success'])
        self.assertIn("Battery capacity", result['error'])
    
    def test_optionally_create_first_car_missing_make(self):
        """Test car creation fails with missing make"""
        # Mock user exists
        mock_user = MagicMock()
        mock_user.id = 1
        self.mock_user_query.get.return_value = mock_user
        
        result = OnboardingService.optionally_create_first_car(
            user_id=1,
            battery_kwh=75.0,
            make="",  # Empty make
            model="Model 3"
        )
        
        self.assertFalse(result['success'])
        self.assertIn("Car make is required", result['error'])
    
    def test_optionally_create_first_car_missing_model(self):
        """Test car creation fails with missing model"""
        # Mock user exists
        mock_user = MagicMock()
        mock_user.id = 1
        self.mock_user_query.get.return_value = mock_user
        
        result = OnboardingService.optionally_create_first_car(
            user_id=1,
            battery_kwh=75.0,
            make="Tesla",
            model=""  # Empty model
        )
        
        self.assertFalse(result['success'])
        self.assertIn("Car model is required", result['error'])
    
    def test_get_onboarding_status_first_run(self):
        """Test get_onboarding_status for first run"""
        # Mock no users
        self.mock_user_query.count.return_value = 0
        
        result = OnboardingService.get_onboarding_status()
        
        self.assertTrue(result['is_first_run'])
        self.assertEqual(result['user_count'], 0)
        self.assertFalse(result['onboarding_complete'])
    
    def test_get_onboarding_status_completed(self):
        """Test get_onboarding_status when onboarding is complete"""
        # Mock users exist
        self.mock_user_query.count.return_value = 1
        
        result = OnboardingService.get_onboarding_status()
        
        self.assertFalse(result['is_first_run'])
        self.assertEqual(result['user_count'], 1)
        self.assertTrue(result['onboarding_complete'])
    
    def test_get_onboarding_status_database_error(self):
        """Test get_onboarding_status handles database errors"""
        # Mock database error
        self.mock_user_query.count.side_effect = Exception("Database error")
        
        result = OnboardingService.get_onboarding_status()
        
        self.assertFalse(result['is_first_run'])
        self.assertEqual(result['user_count'], 0)
        self.assertTrue(result['onboarding_complete'])
        self.assertIn('error', result)


class TestOnboardingIntegration(unittest.TestCase):
    """Integration tests for onboarding functionality"""
    
    def setUp(self):
        """Set up integration test fixtures"""
        # This would require a real database setup for integration tests
        pass
    
    def test_onboarding_flow_simulation(self):
        """Test the complete onboarding flow simulation"""
        # This would test the actual flow with a real database
        # For now, just verify the service methods exist and are callable
        self.assertTrue(hasattr(OnboardingService, 'is_first_run'))
        self.assertTrue(hasattr(OnboardingService, 'create_initial_user'))
        self.assertTrue(hasattr(OnboardingService, 'optionally_create_first_car'))
        self.assertTrue(hasattr(OnboardingService, 'get_onboarding_status'))


def run_tests():
    """Run all onboarding tests"""
    print("Running onboarding unit tests...")
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTest(unittest.makeSuite(TestOnboardingService))
    suite.addTest(unittest.makeSuite(TestOnboardingIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    if result.wasSuccessful():
        print(f"\n✅ All {result.testsRun} tests passed!")
        return True
    else:
        print(f"\n❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for failure in result.failures:
            print(f"FAIL: {failure[0]}")
            print(failure[1])
        for error in result.errors:
            print(f"ERROR: {error[0]}")
            print(error[1])
        return False


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
