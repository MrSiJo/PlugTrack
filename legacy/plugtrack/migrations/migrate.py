#!/usr/bin/env python3
"""
Migration Runner for PlugTrack
Handles baseline squashing and incremental migrations for B7-3.
"""

import os
import sys
import click
from datetime import datetime
from pathlib import Path

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from migration_manager import MigrationManager
from models.user import db
from sqlalchemy import text, inspect


class BaselineMigrationManager(MigrationManager):
    """Enhanced migration manager with baseline squashing support."""
    
    def __init__(self, app=None):
        super().__init__(app)
        self.baseline_migration_id = "008"  # P1-P5 squashed baseline
        
    def is_baseline_applied(self) -> bool:
        """Check if the baseline migration has been applied."""
        try:
            result = db.session.execute(text("""
                SELECT COUNT(*) FROM schema_migrations 
                WHERE migration_id = :baseline_id
            """), {'baseline_id': self.baseline_migration_id})
            return result.scalar() > 0
        except Exception:
            return False
    
    def get_baseline_migration(self):
        """Get the baseline migration (008)."""
        available = self._get_available_migrations()
        return next((m for m in available if m['migration_id'] == self.baseline_migration_id), None)
    
    def get_incremental_migrations(self):
        """Get migrations after the baseline (009+)."""
        available = self._get_available_migrations()
        return [m for m in available if m['migration_id'] > self.baseline_migration_id]
    
    def apply_baseline_then_incremental(self, dry_run: bool = False) -> bool:
        """Apply baseline migration first, then any incremental migrations."""
        print("🚀 PlugTrack Migration Runner (B7-3 Baseline Squashing)")
        print("=" * 60)
        
        if not dry_run:
            self._backup_database()
        
        # Step 1: Check if baseline is needed
        if self.is_baseline_applied():
            print(f"✅ Baseline migration {self.baseline_migration_id} already applied")
        else:
            print(f"🔧 Applying baseline migration {self.baseline_migration_id}...")
            baseline = self.get_baseline_migration()
            if not baseline:
                print(f"❌ Baseline migration {self.baseline_migration_id} not found!")
                return False
            
            if not self.apply_migration(baseline, dry_run):
                return False
        
        # Step 2: Apply any incremental migrations (009+)
        incremental = self.get_incremental_migrations()
        applied = set(self._get_applied_migrations())
        
        pending_incremental = [m for m in incremental if m['migration_id'] not in applied]
        
        if pending_incremental:
            print(f"\n🔧 Applying {len(pending_incremental)} incremental migration(s)...")
            for migration in pending_incremental:
                if not self.apply_migration(migration, dry_run):
                    return False
        else:
            print("✅ No incremental migrations pending")
        
        print(f"\n{'[DRY RUN] ' if dry_run else ''}🎉 Migration process completed successfully!")
        return True
    
    def get_migration_status_detailed(self) -> dict:
        """Get detailed migration status including baseline info."""
        status = self.get_migration_status()
        
        baseline_applied = self.is_baseline_applied()
        incremental = self.get_incremental_migrations()
        applied_incremental = [m for m in incremental if m['migration_id'] in status['applied_migrations']]
        
        return {
            **status,
            'baseline_applied': baseline_applied,
            'baseline_id': self.baseline_migration_id,
            'incremental_count': len(incremental),
            'applied_incremental_count': len(applied_incremental),
            'pending_incremental': [m['migration_id'] for m in incremental if m['migration_id'] not in status['applied_migrations']]
        }


@click.group()
def cli():
    """PlugTrack Migration Runner with Baseline Squashing (B7-3)"""
    pass


@cli.command('status')
def status():
    """Show detailed migration status including baseline info."""
    from __init__ import create_app
    app = create_app()
    
    with app.app_context():
        manager = BaselineMigrationManager(app)
        status = manager.get_migration_status_detailed()
        
        print("📊 Migration Status Report (B7-3)")
        print("=" * 40)
        print(f"Baseline Applied: {'✅' if status['baseline_applied'] else '❌'} (Migration {status['baseline_id']})")
        print(f"Applied Migrations: {status['applied_count']}")
        print(f"Available Migrations: {status['available_count']}")
        print(f"Incremental Migrations: {status['incremental_count']}")
        print(f"Applied Incremental: {status['applied_incremental_count']}")
        
        if status['applied_migrations']:
            print(f"\nApplied Migrations:")
            for migration_id in status['applied_migrations']:
                print(f"  ✅ {migration_id}")
        
        if status['pending_incremental']:
            print(f"\nPending Incremental Migrations:")
            for migration_id in status['pending_incremental']:
                print(f"  ⏳ {migration_id}")
        
        if status['last_applied']:
            print(f"\nLast Applied: {status['last_applied']}")


@cli.command('apply')
@click.option('--dry-run', is_flag=True, help='Show what would be done without applying')
def apply(dry_run):
    """Apply baseline migration then incremental migrations."""
    from __init__ import create_app
    app = create_app()
    
    with app.app_context():
        manager = BaselineMigrationManager(app)
        success = manager.apply_baseline_then_incremental(dry_run)
        
        if not success:
            click.echo("❌ Migration process failed!", err=True)
            sys.exit(1)


@cli.command('fresh-init')
@click.option('--dry-run', is_flag=True, help='Show what would be done without applying')
def fresh_init(dry_run):
    """Initialize a fresh database with baseline + incremental migrations."""
    from __init__ import create_app
    app = create_app()
    
    with app.app_context():
        # Check if database is truly fresh
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        if tables and not dry_run:
            click.echo("❌ Database is not fresh - contains existing tables!", err=True)
            click.echo("Use 'migrate apply' for existing databases or delete the database file first.")
            sys.exit(1)
        
        if dry_run and tables:
            click.echo("⚠️  Database contains existing tables - not truly fresh")
        
        manager = BaselineMigrationManager(app)
        success = manager.apply_baseline_then_incremental(dry_run)
        
        if not success:
            click.echo("❌ Fresh initialization failed!", err=True)
            sys.exit(1)
        
        if not dry_run:
            click.echo("\n🎉 Fresh database initialized successfully!")
            click.echo("You can now start the application and create your first account.")


if __name__ == '__main__':
    cli()
