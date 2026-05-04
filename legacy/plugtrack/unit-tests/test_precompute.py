#!/usr/bin/env python3
"""
Unit tests for precompute functionality
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from services.precompute import PrecomputeService


class TestPrecomputeService(unittest.TestCase):
    """Test cases for PrecomputeService"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock the database session
        self.mock_db_session = MagicMock()
        
        # Patch the database session
        self.db_patcher = patch('services.precompute.db')
        self.mock_db = self.db_patcher.start()
        self.mock_db.session = self.mock_db_session
        
        # Patch the ChargingSession model query
        self.session_query_patcher = patch('services.precompute.ChargingSession.query')
        self.mock_session_query = self.session_query_patcher.start()
        
        # Patch the Car model query
        self.car_query_patcher = patch('services.precompute.Car.query')
        self.mock_car_query = self.car_query_patcher.start()
        
        # Patch the current_app logger
        self.logger_patcher = patch('services.precompute.current_app')
        self.mock_app = self.logger_patcher.start()
        self.mock_app.logger = MagicMock()
        
        # Patch the DerivedMetricsService
        self.metrics_patcher = patch('services.precompute.DerivedMetricsService')
        self.mock_metrics_service = self.metrics_patcher.start()
    
    def tearDown(self):
        """Clean up after tests"""
        self.db_patcher.stop()
        self.session_query_patcher.stop()
        self.car_query_patcher.stop()
        self.logger_patcher.stop()
        self.metrics_patcher.stop()
    
    def test_compute_for_session_success(self):
        """Test successful computation for a specific session"""
        # Mock session and car
        mock_session = MagicMock()
        mock_session.id = 1
        mock_session.car_id = 1
        mock_session.user_id = 1
        self.mock_session_query.get.return_value = mock_session
        
        mock_car = MagicMock()
        mock_car.id = 1
        self.mock_car_query.get.return_value = mock_car
        
        # Mock metrics calculation
        self.mock_metrics_service.calculate_session_metrics.return_value = {
            'efficiency_used': 4.2,
            'cost_per_mile': 0.15,
            'loss_estimate': 5.0
        }
        
        result = PrecomputeService.compute_for_session(1)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['session_id'], 1)
        self.assertEqual(result['metrics']['efficiency_mpkwh'], 4.2)
        self.assertEqual(result['metrics']['pence_per_mile'], 15.0)  # 0.15 * 100
        self.assertEqual(result['metrics']['loss_pct'], 5.0)
        
        # Verify session was updated
        self.assertEqual(mock_session.computed_efficiency_mpkwh, 4.2)
        self.assertEqual(mock_session.computed_pence_per_mile, 15.0)
        self.assertEqual(mock_session.computed_loss_pct, 5.0)
        
        # Verify commit was called
        self.mock_db_session.commit.assert_called_once()
    
    def test_compute_for_session_not_found(self):
        """Test computation fails when session not found"""
        self.mock_session_query.get.return_value = None
        
        result = PrecomputeService.compute_for_session(999)
        
        self.assertFalse(result['success'])
        self.assertIn('Session 999 not found', result['error'])


def run_tests():
    """Run all precompute tests"""
    print("Running precompute unit tests...")
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTest(unittest.makeSuite(TestPrecomputeService))
    
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