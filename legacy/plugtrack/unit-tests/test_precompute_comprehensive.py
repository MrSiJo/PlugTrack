#!/usr/bin/env python3
"""
Comprehensive Precompute Tests for PlugTrack B7-5
Tests precompute hooks, CLI commands, and service functionality.
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

from services.precompute import PrecomputeService
from models.charging_session import ChargingSession
from models.car import Car
from models.user import User
from models.user import db


class TestPrecomputeServiceComprehensive(unittest.TestCase):
    """Comprehensive tests for PrecomputeService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
        
        # Mock database operations
        self.session_query_patcher = patch('models.charging_session.ChargingSession.query')
        self.car_query_patcher = patch('models.car.Car.query')
        self.user_query_patcher = patch('models.user.User.query')
        self.db_session_patcher = patch('models.user.db.session')
        self.derived_metrics_patcher = patch('services.derived_metrics.DerivedMetricsService.calculate_session_metrics')
        self.insights_patcher = patch('services.insights.InsightsService.calculate_loss_estimate')
        
        self.mock_session_query = self.session_query_patcher.start()
        self.mock_car_query = self.car_query_patcher.start()
        self.mock_user_query = self.user_query_patcher.start()
        self.mock_db_session = self.db_session_patcher.start()
        self.mock_derived_metrics = self.derived_metrics_patcher.start()
        self.mock_insights = self.insights_patcher.start()
        
        # Mock objects
        self.mock_user = User(id=1, username='testuser')
        self.mock_car = Car(id=1, user_id=1, make='Tesla', model='Model 3', battery_kwh=75.0)
        self.mock_session = ChargingSession(
            id=1, user_id=1, car_id=1, date=date.today(), odometer=10000,
            charge_type='AC', charge_speed_kw=7.0, location_label='Home',
            charge_delivered_kwh=20.0, duration_mins=120, cost_per_kwh=0.15,
            soc_from=20, soc_to=70,
            computed_efficiency_mpkwh=None, computed_pence_per_mile=None, computed_loss_pct=None
        )
        
        # Setup mock returns
        self.mock_user_query.get.return_value = self.mock_user
        self.mock_car_query.get.return_value = self.mock_car
        self.mock_session_query.get.return_value = self.mock_session
        
        self.mock_derived_metrics.return_value = {
            'efficiency_used': 4.0,
            'cost_per_mile': 0.15,
            'loss_estimate': 10.0
        }
        self.mock_insights.return_value = 10.0
    
    def tearDown(self):
        """Clean up after tests."""
        self.session_query_patcher.stop()
        self.car_query_patcher.stop()
        self.user_query_patcher.stop()
        self.db_session_patcher.stop()
        self.derived_metrics_patcher.stop()
        self.insights_patcher.stop()
    
    def test_compute_for_session_success(self):
        """Test successful session computation."""
        with self.app_context:
            result = PrecomputeService.compute_for_session(1)
            
            self.assertTrue(result['success'])
            self.assertEqual(self.mock_session.computed_efficiency_mpkwh, 4.0)
            self.assertEqual(self.mock_session.computed_pence_per_mile, 15.0)
            self.assertEqual(self.mock_session.computed_loss_pct, 10.0)
            self.mock_db_session.add.assert_called_once_with(self.mock_session)
            self.mock_db_session.commit.assert_called_once()
    
    def test_compute_for_session_not_found(self):
        """Test session computation when session not found."""
        with self.app_context:
            self.mock_session_query.get.return_value = None
            
            result = PrecomputeService.compute_for_session(999)
            
            self.assertFalse(result['success'])
            self.assertIn("not found", result['error'])
            self.mock_db_session.commit.assert_not_called()
    
    def test_compute_for_session_calculation_error(self):
        """Test session computation with calculation error."""
        with self.app_context:
            self.mock_derived_metrics.side_effect = Exception("Calculation error")
            
            result = PrecomputeService.compute_for_session(1)
            
            self.assertFalse(result['success'])
            self.assertIn("Calculation error", result['error'])
            self.app.logger.error.assert_called_once()
    
    def test_compute_for_user_success(self):
        """Test successful user computation."""
        with self.app_context:
            # Mock sessions for user
            sessions = [self.mock_session, MagicMock()]
            sessions[1].id = 2
            self.mock_session_query.filter_by.return_value.all.return_value = sessions
            
            # Mock successful computation for each session
            with patch.object(PrecomputeService, 'compute_for_session') as mock_compute:
                mock_compute.return_value = {'success': True}
                
                result = PrecomputeService.compute_for_user(1)
                
                self.assertTrue(result['success'])
                self.assertEqual(result['total_sessions'], 2)
                self.assertEqual(result['processed'], 2)
                self.assertEqual(mock_compute.call_count, 2)
    
    def test_compute_for_user_with_errors(self):
        """Test user computation with some errors."""
        with self.app_context:
            sessions = [self.mock_session, MagicMock()]
            sessions[1].id = 2
            self.mock_session_query.filter_by.return_value.all.return_value = sessions
            
            # Mock mixed results
            with patch.object(PrecomputeService, 'compute_for_session') as mock_compute:
                mock_compute.side_effect = [
                    {'success': True},
                    {'success': False, 'error': 'Session 2 error'}
                ]
                
                result = PrecomputeService.compute_for_user(1)
                
                self.assertTrue(result['success'])
                self.assertEqual(result['total_sessions'], 2)
                self.assertEqual(result['processed'], 1)
                self.assertEqual(len(result['errors']), 1)
                self.assertEqual(result['errors'][0]['session_id'], 2)
    
    def test_compute_all_success(self):
        """Test successful computation of all sessions."""
        with self.app_context:
            # Mock all sessions
            sessions = [self.mock_session, MagicMock()]
            sessions[1].id = 2
            self.mock_session_query.filter.return_value.all.return_value = sessions
            
            with patch.object(PrecomputeService, 'compute_for_session') as mock_compute:
                mock_compute.return_value = {'success': True}
                
                result = PrecomputeService.compute_all()
                
                self.assertTrue(result['success'])
                self.assertEqual(result['total_sessions'], 2)
                self.assertEqual(result['processed'], 2)
    
    def test_get_metrics_summary_global(self):
        """Test global metrics summary."""
        with self.app_context:
            # Mock query results
            self.mock_session_query.count.return_value = 10
            self.mock_session_query.filter.return_value.count.return_value = 8
            
            result = PrecomputeService.get_metrics_summary()
            
            self.assertTrue(result['success'])
            self.assertEqual(result['total_sessions'], 10)
            self.assertEqual(result['computed_sessions'], 8)
            self.assertEqual(result['pending_sessions'], 2)
            self.assertEqual(result['completion_rate'], 80.0)
    
    def test_get_metrics_summary_user_specific(self):
        """Test user-specific metrics summary."""
        with self.app_context:
            # Mock query results for specific user
            self.mock_session_query.filter_by.return_value.count.return_value = 5
            self.mock_session_query.filter_by.return_value.filter.return_value.count.return_value = 4
            
            result = PrecomputeService.get_metrics_summary(user_id=1)
            
            self.assertTrue(result['success'])
            self.assertEqual(result['total_sessions'], 5)
            self.assertEqual(result['computed_sessions'], 4)
            self.assertEqual(result['pending_sessions'], 1)


class TestPrecomputeHooks(unittest.TestCase):
    """Test precompute hooks in session create/edit routes."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
    
    @patch('routes.charging_sessions.PrecomputeService.compute_for_session')
    @patch('routes.charging_sessions.db.session.commit')
    def test_session_create_hook_success(self, mock_commit, mock_compute):
        """Test precompute hook on session creation."""
        from routes.charging_sessions import new
        
        mock_compute.return_value = {'success': True}
        
        with self.app_context:
            with patch('routes.charging_sessions.current_user') as mock_user:
                mock_user.id = 1
                
                # Mock form and session creation
                with patch('routes.charging_sessions.ChargingSessionForm') as mock_form:
                    mock_form_instance = MagicMock()
                    mock_form_instance.validate_on_submit.return_value = True
                    mock_form_instance.car_id.data = 1
                    mock_form_instance.date.data = date.today()
                    mock_form_instance.odometer.data = 10000
                    mock_form_instance.charge_type.data = 'AC'
                    mock_form_instance.charge_speed_kw.data = 7.0
                    mock_form_instance.location_label.data = 'Home'
                    mock_form_instance.charge_delivered_kwh.data = 20.0
                    mock_form_instance.duration_mins.data = 120
                    mock_form_instance.cost_per_kwh.data = 0.15
                    mock_form_instance.soc_from.data = 20
                    mock_form_instance.soc_to.data = 70
                    mock_form.return_value = mock_form_instance
                    
                    with patch('routes.charging_sessions.ChargingSession') as mock_session_class:
                        mock_session = MagicMock()
                        mock_session.id = 1
                        mock_session_class.return_value = mock_session
                        
                        # Mock the route function
                        with patch('routes.charging_sessions.render_template') as mock_render:
                            mock_render.return_value = "rendered_template"
                            
                            result = new()
                            
                            # Verify precompute was called
                            mock_compute.assert_called_once_with(1)
    
    @patch('routes.charging_sessions.PrecomputeService.compute_for_session')
    @patch('routes.charging_sessions.db.session.commit')
    def test_session_edit_hook_success(self, mock_commit, mock_compute):
        """Test precompute hook on session edit."""
        from routes.charging_sessions import edit
        
        mock_compute.return_value = {'success': True}
        
        with self.app_context:
            with patch('routes.charging_sessions.current_user') as mock_user:
                mock_user.id = 1
                
                # Mock session lookup and form
                with patch('routes.charging_sessions.ChargingSession.query') as mock_query:
                    mock_session = MagicMock()
                    mock_session.id = 1
                    mock_session.user_id = 1
                    mock_query.get.return_value = mock_session
                    
                    with patch('routes.charging_sessions.ChargingSessionForm') as mock_form:
                        mock_form_instance = MagicMock()
                        mock_form_instance.validate_on_submit.return_value = True
                        mock_form_instance.car_id.data = 1
                        mock_form_instance.date.data = date.today()
                        mock_form_instance.odometer.data = 10000
                        mock_form_instance.charge_type.data = 'AC'
                        mock_form_instance.charge_speed_kw.data = 7.0
                        mock_form_instance.location_label.data = 'Home'
                        mock_form_instance.charge_delivered_kwh.data = 20.0
                        mock_form_instance.duration_mins.data = 120
                        mock_form_instance.cost_per_kwh.data = 0.15
                        mock_form_instance.soc_from.data = 20
                        mock_form_instance.soc_to.data = 70
                        mock_form.return_value = mock_form_instance
                        
                        with patch('routes.charging_sessions.render_template') as mock_render:
                            mock_render.return_value = "rendered_template"
                            
                            result = edit(1)
                            
                            # Verify precompute was called
                            mock_compute.assert_called_once_with(1)
    
    @patch('routes.charging_sessions.PrecomputeService.compute_for_session')
    def test_precompute_hook_error_handling(self, mock_compute):
        """Test precompute hook error handling."""
        from routes.charging_sessions import new
        
        mock_compute.return_value = {'success': False, 'error': 'Precompute failed'}
        
        with self.app_context:
            with patch('routes.charging_sessions.current_user') as mock_user:
                mock_user.id = 1
                
                with patch('routes.charging_sessions.ChargingSessionForm') as mock_form:
                    mock_form_instance = MagicMock()
                    mock_form_instance.validate_on_submit.return_value = True
                    mock_form_instance.car_id.data = 1
                    mock_form_instance.date.data = date.today()
                    mock_form_instance.odometer.data = 10000
                    mock_form_instance.charge_type.data = 'AC'
                    mock_form_instance.charge_speed_kw.data = 7.0
                    mock_form_instance.location_label.data = 'Home'
                    mock_form_instance.charge_delivered_kwh.data = 20.0
                    mock_form_instance.duration_mins.data = 120
                    mock_form_instance.cost_per_kwh.data = 0.15
                    mock_form_instance.soc_from.data = 20
                    mock_form_instance.soc_to.data = 70
                    mock_form.return_value = mock_form_instance
                    
                    with patch('routes.charging_sessions.ChargingSession') as mock_session_class:
                        mock_session = MagicMock()
                        mock_session.id = 1
                        mock_session_class.return_value = mock_session
                        
                        with patch('routes.charging_sessions.render_template') as mock_render:
                            mock_render.return_value = "rendered_template"
                            
                            result = new()
                            
                            # Verify warning was logged
                            self.app.logger.warning.assert_called_once()
                            self.assertIn("Failed to precompute", str(self.app.logger.warning.call_args))


class TestPrecomputeCLI(unittest.TestCase):
    """Test precompute CLI command functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
    
    @patch('__init__.PrecomputeService.compute_for_session')
    def test_cli_recompute_session_success(self, mock_compute):
        """Test CLI recompute specific session success."""
        from __init__ import recompute_sessions
        
        mock_compute.return_value = {
            'success': True,
            'metrics': {
                'efficiency_mpkwh': 4.0,
                'pence_per_mile': 15.0,
                'loss_pct': 10.0
            }
        }
        
        with self.app_context:
            with patch('__init__.CLIOutput') as mock_output_class:
                mock_output = MagicMock()
                mock_output_class.return_value = mock_output
                
                # Test successful session recomputation
                recompute_sessions(
                    recompute_all=False, user_id=None, session_id=1, 
                    force=False, summary=False, verbose=False, quiet=False, examples=False
                )
                
                mock_compute.assert_called_once_with(1)
                mock_output.success.assert_called_once()
    
    @patch('__init__.PrecomputeService.compute_all')
    def test_cli_recompute_all_success(self, mock_compute):
        """Test CLI recompute all sessions success."""
        from __init__ import recompute_sessions
        
        mock_compute.return_value = {
            'success': True,
            'message': 'All sessions processed',
            'total_sessions': 10,
            'processed': 10,
            'errors': []
        }
        
        with self.app_context:
            with patch('__init__.CLIOutput') as mock_output_class:
                mock_output = MagicMock()
                mock_output_class.return_value = mock_output
                
                recompute_sessions(
                    recompute_all=True, user_id=None, session_id=None, 
                    force=False, summary=False, verbose=False, quiet=False, examples=False
                )
                
                mock_compute.assert_called_once_with(force_recompute=False)
                mock_output.success.assert_called_once()
    
    @patch('__init__.PrecomputeService.get_metrics_summary')
    def test_cli_recompute_summary_success(self, mock_summary):
        """Test CLI recompute summary success."""
        from __init__ import recompute_sessions
        
        mock_summary.return_value = {
            'success': True,
            'total_sessions': 10,
            'computed_sessions': 8,
            'pending_sessions': 2,
            'completion_rate': 80.0
        }
        
        with self.app_context:
            with patch('__init__.CLIOutput') as mock_output_class:
                mock_output = MagicMock()
                mock_output_class.return_value = mock_output
                
                recompute_sessions(
                    recompute_all=False, user_id=None, session_id=None, 
                    force=False, summary=True, verbose=False, quiet=False, examples=False
                )
                
                mock_summary.assert_called_once()
                mock_output.echo.assert_called()
    
    def test_cli_recompute_examples(self):
        """Test CLI recompute examples."""
        from __init__ import recompute_sessions
        
        with self.app_context:
            with patch('__init__.show_examples') as mock_show_examples:
                recompute_sessions(
                    recompute_all=False, user_id=None, session_id=None, 
                    force=False, summary=False, verbose=False, quiet=False, examples=True
                )
                
                mock_show_examples.assert_called_once_with('recompute-sessions')
    
    def test_cli_recompute_verbose_quiet_conflict(self):
        """Test CLI recompute verbose and quiet conflict."""
        from __init__ import recompute_sessions
        
        with self.app_context:
            with patch('__init__.sys.exit') as mock_exit:
                recompute_sessions(
                    recompute_all=False, user_id=None, session_id=None, 
                    force=False, summary=False, verbose=True, quiet=True, examples=False
                )
                
                mock_exit.assert_called_once_with(1)


if __name__ == '__main__':
    print("Running comprehensive precompute tests...")
    unittest.main()
