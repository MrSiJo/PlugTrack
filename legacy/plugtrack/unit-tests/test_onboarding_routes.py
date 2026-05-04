#!/usr/bin/env python3
"""
Unit tests for onboarding routes
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from routes.onboarding import onboarding_bp
from services.onboarding import OnboardingService
from services.forms import OnboardingUserForm, OnboardingCarForm


class TestOnboardingRoutes(unittest.TestCase):
    """Test cases for onboarding routes"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock Flask app and request context
        self.app_patcher = patch('routes.onboarding.current_app')
        self.mock_app = self.app_patcher.start()
        
        # Mock Flask-Login current_user
        self.current_user_patcher = patch('routes.onboarding.current_user')
        self.mock_current_user = self.current_user_patcher.start()
        self.mock_current_user.is_authenticated = False
        
        # Mock Flask request
        self.request_patcher = patch('routes.onboarding.request')
        self.mock_request = self.request_patcher.start()
        
        # Mock Flask redirect and url_for
        self.redirect_patcher = patch('routes.onboarding.redirect')
        self.mock_redirect = self.redirect_patcher.start()
        
        self.url_for_patcher = patch('routes.onboarding.url_for')
        self.mock_url_for = self.url_for_patcher.start()
        
        # Mock Flask render_template
        self.render_template_patcher = patch('routes.onboarding.render_template')
        self.mock_render_template = self.render_template_patcher.start()
        
        # Mock Flask flash
        self.flash_patcher = patch('routes.onboarding.flash')
        self.mock_flash = self.flash_patcher.start()
        
        # Mock login_user
        self.login_user_patcher = patch('routes.onboarding.login_user')
        self.mock_login_user = self.login_user_patcher.start()
        
        # Mock OnboardingService
        self.onboarding_service_patcher = patch('routes.onboarding.OnboardingService')
        self.mock_onboarding_service = self.onboarding_service_patcher.start()
        
        # Mock User model
        self.user_patcher = patch('routes.onboarding.User')
        self.mock_user_class = self.user_patcher.start()
        
        # Mock forms
        self.user_form_patcher = patch('routes.onboarding.OnboardingUserForm')
        self.mock_user_form_class = self.user_form_patcher.start()
        
        self.car_form_patcher = patch('routes.onboarding.OnboardingCarForm')
        self.mock_car_form_class = self.car_form_patcher.start()
    
    def tearDown(self):
        """Clean up after tests"""
        self.app_patcher.stop()
        self.current_user_patcher.stop()
        self.request_patcher.stop()
        self.redirect_patcher.stop()
        self.url_for_patcher.stop()
        self.render_template_patcher.stop()
        self.flash_patcher.stop()
        self.login_user_patcher.stop()
        self.onboarding_service_patcher.stop()
        self.user_patcher.stop()
        self.user_form_patcher.stop()
        self.car_form_patcher.stop()
    
    def test_welcome_route_first_run(self):
        """Test welcome route when it's first run"""
        # Mock first run
        self.mock_onboarding_service.is_first_run.return_value = True
        
        # Mock form
        mock_form = MagicMock()
        self.mock_user_form_class.return_value = mock_form
        
        # Test the route
        from routes.onboarding import welcome
        result = welcome()
        
        # Verify redirect to login (due to guard)
        self.mock_redirect.assert_called_once()
    
    def test_welcome_route_not_first_run(self):
        """Test welcome route when it's not first run"""
        # Mock not first run
        self.mock_onboarding_service.is_first_run.return_value = False
        
        # Test the route
        from routes.onboarding import welcome
        result = welcome()
        
        # Should redirect to login
        self.mock_redirect.assert_called_once()
    
    def test_create_user_route_get(self):
        """Test create_user route GET request"""
        # Mock first run
        self.mock_onboarding_service.is_first_run.return_value = True
        
        # Mock form
        mock_form = MagicMock()
        self.mock_user_form_class.return_value = mock_form
        
        # Test the route
        from routes.onboarding import create_user
        result = create_user()
        
        # Should render template
        self.mock_render_template.assert_called_once()
    
    def test_create_user_route_post_success(self):
        """Test create_user route POST request with successful user creation"""
        # Mock first run
        self.mock_onboarding_service.is_first_run.return_value = True
        
        # Mock form validation
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.username.data = "testuser"
        mock_form.password.data = "password123"
        self.mock_user_form_class.return_value = mock_form
        
        # Mock successful user creation
        self.mock_onboarding_service.create_initial_user.return_value = {
            'success': True,
            'user': {'id': 1, 'username': 'testuser', 'created_at': '2024-01-01'}
        }
        
        # Mock user query
        mock_user = MagicMock()
        self.mock_user_class.query.get.return_value = mock_user
        
        # Test the route
        from routes.onboarding import create_user
        result = create_user()
        
        # Verify user creation was called
        self.mock_onboarding_service.create_initial_user.assert_called_once_with(
            username="testuser",
            password="password123"
        )
        
        # Verify user login
        self.mock_login_user.assert_called_once_with(mock_user)
        
        # Verify redirect to create_car
        self.mock_redirect.assert_called_once()
    
    def test_create_user_route_post_failure(self):
        """Test create_user route POST request with failed user creation"""
        # Mock first run
        self.mock_onboarding_service.is_first_run.return_value = True
        
        # Mock form validation
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.username.data = "testuser"
        mock_form.password.data = "password123"
        self.mock_user_form_class.return_value = mock_form
        
        # Mock failed user creation
        self.mock_onboarding_service.create_initial_user.return_value = {
            'success': False,
            'error': 'Username already exists'
        }
        
        # Test the route
        from routes.onboarding import create_user
        result = create_user()
        
        # Verify error flash
        self.mock_flash.assert_called_once_with('Username already exists', 'error')
        
        # Should render template with form
        self.mock_render_template.assert_called_once()
    
    def test_create_car_route_not_authenticated(self):
        """Test create_car route when user is not authenticated"""
        # Mock user not authenticated
        self.mock_current_user.is_authenticated = False
        
        # Test the route
        from routes.onboarding import create_car
        result = create_car()
        
        # Should redirect to welcome
        self.mock_redirect.assert_called_once()
    
    def test_create_car_route_get(self):
        """Test create_car route GET request"""
        # Mock user authenticated
        self.mock_current_user.is_authenticated = True
        
        # Mock form
        mock_form = MagicMock()
        self.mock_car_form_class.return_value = mock_form
        
        # Test the route
        from routes.onboarding import create_car
        result = create_car()
        
        # Should render template
        self.mock_render_template.assert_called_once()
    
    def test_create_car_route_post_with_car_data(self):
        """Test create_car route POST request with car data"""
        # Mock user authenticated
        self.mock_current_user.is_authenticated = True
        self.mock_current_user.id = 1
        
        # Mock form validation
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.make.data = "Tesla"
        mock_form.model.data = "Model 3"
        mock_form.battery_kwh.data = 75.0
        mock_form.efficiency_mpkwh.data = 4.2
        self.mock_car_form_class.return_value = mock_form
        
        # Mock successful car creation
        self.mock_onboarding_service.optionally_create_first_car.return_value = {
            'success': True,
            'car': {'id': 1, 'make': 'Tesla', 'model': 'Model 3'}
        }
        
        # Test the route
        from routes.onboarding import create_car
        result = create_car()
        
        # Verify car creation was called
        self.mock_onboarding_service.optionally_create_first_car.assert_called_once_with(
            user_id=1,
            make="Tesla",
            model="Model 3",
            battery_kwh=75.0,
            efficiency_mpkwh=4.2
        )
        
        # Verify success flash
        self.mock_flash.assert_called_once_with('Car added successfully! You can add more cars later.', 'success')
        
        # Verify redirect to dashboard
        self.mock_redirect.assert_called_once()
    
    def test_create_car_route_post_no_car_data(self):
        """Test create_car route POST request with no car data"""
        # Mock user authenticated
        self.mock_current_user.is_authenticated = True
        self.mock_current_user.id = 1
        
        # Mock form validation
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.make.data = ""
        mock_form.model.data = ""
        mock_form.battery_kwh.data = None
        self.mock_car_form_class.return_value = mock_form
        
        # Test the route
        from routes.onboarding import create_car
        result = create_car()
        
        # Verify info flash
        self.mock_flash.assert_called_once_with('No car data provided. You can add cars later from the Cars page.', 'info')
        
        # Verify redirect to dashboard
        self.mock_redirect.assert_called_once()
    
    def test_skip_car_route_not_authenticated(self):
        """Test skip_car route when user is not authenticated"""
        # Mock user not authenticated
        self.mock_current_user.is_authenticated = False
        
        # Test the route
        from routes.onboarding import skip_car
        result = skip_car()
        
        # Should redirect to welcome
        self.mock_redirect.assert_called_once()
    
    def test_skip_car_route_authenticated(self):
        """Test skip_car route when user is authenticated"""
        # Mock user authenticated
        self.mock_current_user.is_authenticated = True
        
        # Test the route
        from routes.onboarding import skip_car
        result = skip_car()
        
        # Verify info flash
        self.mock_flash.assert_called_once_with('You can add cars later from the Cars page.', 'info')
        
        # Verify redirect to dashboard
        self.mock_redirect.assert_called_once()
    
    def test_status_route(self):
        """Test status route"""
        # Mock status data
        self.mock_onboarding_service.get_onboarding_status.return_value = {
            'is_first_run': True,
            'user_count': 0,
            'onboarding_complete': False
        }
        
        # Test the route
        from routes.onboarding import status
        result = status()
        
        # Verify service was called
        self.mock_onboarding_service.get_onboarding_status.assert_called_once()


def run_tests():
    """Run all onboarding route tests"""
    print("Running onboarding route unit tests...")
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTest(unittest.makeSuite(TestOnboardingRoutes))
    
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
