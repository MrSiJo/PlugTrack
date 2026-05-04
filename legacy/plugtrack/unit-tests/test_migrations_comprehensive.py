#!/usr/bin/env python3
"""
Comprehensive Migration Tests for PlugTrack B7-5
Tests fresh init, upgrade paths, and migration system functionality.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call
from datetime import datetime

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from migrations.migration_manager import MigrationManager
from migrations.migrate import BaselineMigrationManager


class TestMigrationSystemComprehensive(unittest.TestCase):
    """Comprehensive tests for migration system."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config = {'DATABASE_URL': 'sqlite:///test.db'}
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
        
        # Mock database operations
        self.db_session_patcher = patch('models.user.db.session')
        self.inspect_patcher = patch('sqlalchemy.inspect')
        self.text_patcher = patch('sqlalchemy.text')
        
        self.mock_db_session = self.db_session_patcher.start()
        self.mock_inspect = self.inspect_patcher.start()
        self.mock_text = self.text_patcher.start()
        
        # Mock inspector
        self.mock_inspector = MagicMock()
        self.mock_inspect.return_value = self.mock_inspector
    
    def tearDown(self):
        """Clean up after tests."""
        self.db_session_patcher.stop()
        self.inspect_patcher.stop()
        self.text_patcher.stop()
    
    def test_migration_manager_initialization(self):
        """Test migration manager initialization."""
        manager = MigrationManager(self.app)
        
        self.assertEqual(manager.app, self.app)
        self.assertIsNotNone(manager.migrations_dir)
    
    def test_ensure_migration_table(self):
        """Test migration table creation."""
        manager = MigrationManager(self.app)
        
        with self.app_context:
            manager._ensure_migration_table()
            
            # Verify table creation was called
            self.mock_db_session.execute.assert_called()
            self.mock_db_session.commit.assert_called_once()
    
    def test_get_applied_migrations_empty(self):
        """Test getting applied migrations when none exist."""
        manager = MigrationManager(self.app)
        
        with self.app_context:
            # Mock empty result
            self.mock_db_session.execute.return_value.fetchall.return_value = []
            
            applied = manager._get_applied_migrations()
            
            self.assertEqual(applied, [])
    
    def test_get_applied_migrations_with_data(self):
        """Test getting applied migrations with existing data."""
        manager = MigrationManager(self.app)
        
        with self.app_context:
            # Mock existing migrations
            self.mock_db_session.execute.return_value.fetchall.return_value = [
                ('001',), ('002',), ('003',)
            ]
            
            applied = manager._get_applied_migrations()
            
            self.assertEqual(applied, ['001', '002', '003'])
    
    def test_is_fresh_database_true(self):
        """Test fresh database detection."""
        manager = MigrationManager(self.app)
        
        with self.app_context:
            self.mock_inspector.get_table_names.return_value = []
            
            result = manager.is_fresh_database()
            
            self.assertTrue(result)
    
    def test_is_fresh_database_false(self):
        """Test non-fresh database detection."""
        manager = MigrationManager(self.app)
        
        with self.app_context:
            self.mock_inspector.get_table_names.return_value = ['user', 'car']
            
            result = manager.is_fresh_database()
            
            self.assertFalse(result)
    
    def test_apply_migration_success(self):
        """Test successful migration application."""
        manager = MigrationManager(self.app)
        
        migration = {
            'migration_id': '001',
            'description': 'Test migration',
            'upgrade': MagicMock()
        }
        
        with self.app_context:
            result = manager.apply_migration(migration, dry_run=False)
            
            self.assertTrue(result)
            migration['upgrade'].assert_called_once()
            self.mock_db_session.execute.assert_called()
            self.mock_db_session.commit.assert_called_once()
    
    def test_apply_migration_dry_run(self):
        """Test migration dry run."""
        manager = MigrationManager(self.app)
        
        migration = {
            'migration_id': '001',
            'description': 'Test migration',
            'upgrade': MagicMock()
        }
        
        with self.app_context:
            result = manager.apply_migration(migration, dry_run=True)
            
            self.assertTrue(result)
            migration['upgrade'].assert_not_called()
            self.mock_db_session.execute.assert_not_called()
    
    def test_apply_migration_failure(self):
        """Test migration application failure."""
        manager = MigrationManager(self.app)
        
        migration = {
            'migration_id': '001',
            'description': 'Test migration',
            'upgrade': MagicMock(side_effect=Exception("Migration failed"))
        }
        
        with self.app_context:
            with self.assertRaises(Exception):
                manager.apply_migration(migration, dry_run=False)
            
            self.mock_db_session.rollback.assert_called_once()


class TestBaselineMigrationManager(unittest.TestCase):
    """Test baseline migration manager functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config = {'DATABASE_URL': 'sqlite:///test.db'}
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
        
        # Mock database operations
        self.db_session_patcher = patch('models.user.db.session')
        self.inspect_patcher = patch('sqlalchemy.inspect')
        self.text_patcher = patch('sqlalchemy.text')
        
        self.mock_db_session = self.db_session_patcher.start()
        self.mock_inspect = self.inspect_patcher.start()
        self.mock_text = self.text_patcher.start()
        
        # Mock inspector
        self.mock_inspector = MagicMock()
        self.mock_inspect.return_value = self.mock_inspector
    
    def tearDown(self):
        """Clean up after tests."""
        self.db_session_patcher.stop()
        self.inspect_patcher.stop()
        self.text_patcher.stop()
    
    def test_baseline_migration_manager_initialization(self):
        """Test baseline migration manager initialization."""
        manager = BaselineMigrationManager(self.app)
        
        self.assertEqual(manager.app, self.app)
        self.assertEqual(manager.baseline_migration_id, "008")
    
    def test_is_baseline_applied_true(self):
        """Test baseline applied detection."""
        manager = BaselineMigrationManager(self.app)
        
        with self.app_context:
            self.mock_db_session.execute.return_value.scalar.return_value = 1
            
            result = manager.is_baseline_applied()
            
            self.assertTrue(result)
    
    def test_is_baseline_applied_false(self):
        """Test baseline not applied detection."""
        manager = BaselineMigrationManager(self.app)
        
        with self.app_context:
            self.mock_db_session.execute.return_value.scalar.return_value = 0
            
            result = manager.is_baseline_applied()
            
            self.assertFalse(result)
    
    def test_get_baseline_migration(self):
        """Test getting baseline migration."""
        manager = BaselineMigrationManager(self.app)
        
        with patch.object(manager, '_get_available_migrations') as mock_get_available:
            mock_migration = {'migration_id': '008', 'description': 'Baseline'}
            mock_get_available.return_value = [mock_migration]
            
            result = manager.get_baseline_migration()
            
            self.assertEqual(result, mock_migration)
    
    def test_get_incremental_migrations(self):
        """Test getting incremental migrations."""
        manager = BaselineMigrationManager(self.app)
        
        with patch.object(manager, '_get_available_migrations') as mock_get_available:
            mock_migrations = [
                {'migration_id': '007', 'description': 'Old'},
                {'migration_id': '008', 'description': 'Baseline'},
                {'migration_id': '009', 'description': 'Incremental 1'},
                {'migration_id': '010', 'description': 'Incremental 2'}
            ]
            mock_get_available.return_value = mock_migrations
            
            result = manager.get_incremental_migrations()
            
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]['migration_id'], '009')
            self.assertEqual(result[1]['migration_id'], '010')
    
    def test_apply_baseline_then_incremental_baseline_exists(self):
        """Test applying baseline when it already exists."""
        manager = BaselineMigrationManager(self.app)
        
        with self.app_context:
            with patch.object(manager, 'is_baseline_applied', return_value=True):
                with patch.object(manager, 'get_incremental_migrations', return_value=[]):
                    with patch.object(manager, '_backup_database') as mock_backup:
                        result = manager.apply_baseline_then_incremental(dry_run=False)
                        
                        self.assertTrue(result)
                        mock_backup.assert_called_once()
    
    def test_apply_baseline_then_incremental_fresh_database(self):
        """Test applying baseline to fresh database."""
        manager = BaselineMigrationManager(self.app)
        
        with self.app_context:
            with patch.object(manager, 'is_baseline_applied', return_value=False):
                with patch.object(manager, 'get_baseline_migration') as mock_get_baseline:
                    with patch.object(manager, 'get_incremental_migrations', return_value=[]):
                        with patch.object(manager, 'apply_migration') as mock_apply:
                            with patch.object(manager, '_backup_database') as mock_backup:
                                mock_baseline = {'migration_id': '008', 'description': 'Baseline'}
                                mock_get_baseline.return_value = mock_baseline
                                mock_apply.return_value = True
                                
                                result = manager.apply_baseline_then_incremental(dry_run=False)
                                
                                self.assertTrue(result)
                                mock_apply.assert_called_once_with(mock_baseline, dry_run=False)
    
    def test_get_migration_status_detailed(self):
        """Test detailed migration status."""
        manager = BaselineMigrationManager(self.app)
        
        with self.app_context:
            with patch.object(manager, 'get_migration_status') as mock_get_status:
                with patch.object(manager, 'is_baseline_applied', return_value=True):
                    with patch.object(manager, 'get_incremental_migrations') as mock_get_incremental:
                        mock_get_status.return_value = {
                            'applied_count': 5,
                            'available_count': 8,
                            'pending_count': 3,
                            'applied_migrations': ['001', '002', '003', '004', '005'],
                            'pending_migrations': ['006', '007', '008']
                        }
                        mock_get_incremental.return_value = [
                            {'migration_id': '009'}, {'migration_id': '010'}
                        ]
                        
                        result = manager.get_migration_status_detailed()
                        
                        self.assertTrue(result['baseline_applied'])
                        self.assertEqual(result['baseline_id'], '008')
                        self.assertEqual(result['incremental_count'], 2)
                        self.assertEqual(result['applied_incremental_count'], 0)


class TestMigrationCLI(unittest.TestCase):
    """Test migration CLI commands."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config = {'DATABASE_URL': 'sqlite:///test.db'}
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
    
    @patch('migrations.migrate.BaselineMigrationManager')
    def test_cli_status_command(self, mock_manager_class):
        """Test CLI status command."""
        from migrations.migrate import status
        
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.get_migration_status_detailed.return_value = {
            'baseline_applied': True,
            'baseline_id': '008',
            'applied_count': 5,
            'available_count': 8,
            'incremental_count': 2,
            'applied_incremental_count': 1,
            'applied_migrations': ['001', '002', '003', '004', '005'],
            'pending_incremental': ['009']
        }
        
        with self.app_context:
            with patch('migrations.migrate.create_app', return_value=self.app):
                with patch('migrations.migrate.click.echo') as mock_echo:
                    status()
                    
                    mock_manager.get_migration_status_detailed.assert_called_once()
                    mock_echo.assert_called()
    
    @patch('migrations.migrate.BaselineMigrationManager')
    def test_cli_apply_command(self, mock_manager_class):
        """Test CLI apply command."""
        from migrations.migrate import apply
        
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.apply_baseline_then_incremental.return_value = True
        
        with self.app_context:
            with patch('migrations.migrate.create_app', return_value=self.app):
                with patch('migrations.migrate.click.echo') as mock_echo:
                    apply(dry_run=False)
                    
                    mock_manager.apply_baseline_then_incremental.assert_called_once_with(dry_run=False)
    
    @patch('migrations.migrate.BaselineMigrationManager')
    def test_cli_fresh_init_command(self, mock_manager_class):
        """Test CLI fresh init command."""
        from migrations.migrate import fresh_init
        
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.apply_baseline_then_incremental.return_value = True
        
        with self.app_context:
            with patch('migrations.migrate.create_app', return_value=self.app):
                with patch('migrations.migrate.inspect') as mock_inspect:
                    with patch('migrations.migrate.click.echo') as mock_echo:
                        # Mock fresh database
                        mock_inspector = MagicMock()
                        mock_inspector.get_table_names.return_value = []
                        mock_inspect.return_value = mock_inspector
                        
                        fresh_init(dry_run=False)
                        
                        mock_manager.apply_baseline_then_incremental.assert_called_once_with(dry_run=False)
    
    @patch('migrations.migrate.BaselineMigrationManager')
    def test_cli_fresh_init_existing_database(self, mock_manager_class):
        """Test CLI fresh init with existing database."""
        from migrations.migrate import fresh_init
        
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        
        with self.app_context:
            with patch('migrations.migrate.create_app', return_value=self.app):
                with patch('migrations.migrate.inspect') as mock_inspect:
                    with patch('migrations.migrate.click.echo') as mock_echo:
                        with patch('migrations.migrate.sys.exit') as mock_exit:
                            # Mock existing database
                            mock_inspector = MagicMock()
                            mock_inspector.get_table_names.return_value = ['user', 'car']
                            mock_inspect.return_value = mock_inspector
                            
                            fresh_init(dry_run=False)
                            
                            mock_exit.assert_called_once_with(1)


class TestMigrationIntegration(unittest.TestCase):
    """Integration tests for migration system."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config = {'DATABASE_URL': 'sqlite:///test.db'}
        self.app_context = self.app.app_context.return_value
        self.app_context.__enter__.return_value = self.app
        self.app_context.__exit__.return_value = None
    
    @patch('migrations.migrate.BaselineMigrationManager')
    def test_fresh_database_initialization_flow(self, mock_manager_class):
        """Test complete fresh database initialization flow."""
        from migrations.migrate import fresh_init
        
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.apply_baseline_then_incremental.return_value = True
        
        with self.app_context:
            with patch('migrations.migrate.create_app', return_value=self.app):
                with patch('migrations.migrate.inspect') as mock_inspect:
                    with patch('migrations.migrate.click.echo') as mock_echo:
                        # Mock fresh database
                        mock_inspector = MagicMock()
                        mock_inspector.get_table_names.return_value = []
                        mock_inspect.return_value = mock_inspector
                        
                        result = fresh_init(dry_run=False)
                        
                        # Verify the flow
                        mock_manager.apply_baseline_then_incremental.assert_called_once_with(dry_run=False)
                        mock_echo.assert_called()
    
    @patch('migrations.migrate.BaselineMigrationManager')
    def test_existing_database_upgrade_flow(self, mock_manager_class):
        """Test existing database upgrade flow."""
        from migrations.migrate import apply
        
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.apply_baseline_then_incremental.return_value = True
        
        with self.app_context:
            with patch('migrations.migrate.create_app', return_value=self.app):
                with patch('migrations.migrate.click.echo') as mock_echo:
                    result = apply(dry_run=False)
                    
                    # Verify the flow
                    mock_manager.apply_baseline_then_incremental.assert_called_once_with(dry_run=False)
                    mock_echo.assert_called()


if __name__ == '__main__':
    print("Running comprehensive migration tests...")
    unittest.main()
