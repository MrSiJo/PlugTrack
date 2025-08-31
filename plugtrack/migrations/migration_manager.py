#!/usr/bin/env python3
"""
Migration Manager for PlugTrack
Handles database schema versioning, migration execution, and rollbacks.
"""

import os
import sys
import importlib.util
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from models.user import db
from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError


class MigrationManager:
    """Manages database migrations with version tracking and rollback support."""
    
    def __init__(self, app=None):
        self.app = app
        self.migrations_dir = Path(__file__).parent / 'versions'
        self.migrations_dir.mkdir(exist_ok=True)
        
    def _ensure_migration_table(self):
        """Create the schema_migrations table if it doesn't exist."""
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_id VARCHAR(10) NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rollback_sql TEXT
                )
            """))
            db.session.commit()
        except Exception as e:
            print(f"Error creating migration table: {e}")
            raise
    
    def _get_applied_migrations(self) -> List[str]:
        """Get list of already applied migration IDs."""
        try:
            result = db.session.execute(text(
                "SELECT migration_id FROM schema_migrations ORDER BY migration_id"
            ))
            return [row[0] for row in result.fetchall()]
        except Exception:
            # Table doesn't exist yet
            return []
    
    def _load_migration_file(self, filepath: Path) -> Optional[Dict]:
        """Load a migration file and return its functions and metadata."""
        try:
            spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            return {
                'upgrade': getattr(module, 'upgrade', None),
                'downgrade': getattr(module, 'downgrade', None),
                'migration_id': getattr(module, 'MIGRATION_ID', None),
                'description': getattr(module, 'DESCRIPTION', ''),
                'dependencies': getattr(module, 'DEPENDENCIES', []),
                'filepath': filepath
            }
        except Exception as e:
            print(f"Error loading migration {filepath}: {e}")
            return None
    
    def _get_available_migrations(self) -> List[Dict]:
        """Get all available migration files, sorted by ID."""
        migrations = []
        
        for filepath in self.migrations_dir.glob('*.py'):
            if filepath.name.startswith('__'):
                continue
                
            migration = self._load_migration_file(filepath)
            if migration and migration['migration_id']:
                migrations.append(migration)
        
        # Sort by migration ID
        migrations.sort(key=lambda x: x['migration_id'])
        return migrations
    
    def _check_dependencies(self, migration: Dict, applied_migrations: List[str]) -> bool:
        """Check if all dependencies for a migration are satisfied."""
        for dep in migration.get('dependencies', []):
            if dep not in applied_migrations:
                return False
        return True
    
    def get_pending_migrations(self) -> List[Dict]:
        """Get list of migrations that need to be applied."""
        self._ensure_migration_table()
        applied = set(self._get_applied_migrations())
        available = self._get_available_migrations()
        
        pending = []
        for migration in available:
            if migration['migration_id'] not in applied:
                if self._check_dependencies(migration, list(applied)):
                    pending.append(migration)
                else:
                    print(f"⚠️  Migration {migration['migration_id']} has unmet dependencies: {migration['dependencies']}")
        
        return pending
    
    def _backup_database(self) -> Optional[str]:
        """Create a backup of the database before applying migrations."""
        try:
            # For SQLite, copy the database file
            db_path = self.app.config.get('DATABASE_URL', '').replace('sqlite:///', '')
            if not db_path or not os.path.exists(db_path):
                print("⚠️  Could not determine database path for backup")
                return None
            
            backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            import shutil
            shutil.copy2(db_path, backup_path)
            print(f"✅ Database backed up to: {backup_path}")
            return backup_path
        except Exception as e:
            print(f"⚠️  Could not create backup: {e}")
            return None
    
    def apply_migration(self, migration: Dict, dry_run: bool = False) -> bool:
        """Apply a single migration."""
        migration_id = migration['migration_id']
        description = migration['description']
        
        print(f"{'[DRY RUN] ' if dry_run else ''}🔧 Applying migration {migration_id}: {description}")
        
        if dry_run:
            print(f"   Would execute migration {migration_id}")
            return True
        
        try:
            # Execute the upgrade function
            if migration['upgrade']:
                migration['upgrade']()
            
            # Record the migration as applied
            db.session.execute(text("""
                INSERT INTO schema_migrations (migration_id, description)
                VALUES (:migration_id, :description)
            """), {
                'migration_id': migration_id,
                'description': description
            })
            
            db.session.commit()
            print(f"✅ Migration {migration_id} applied successfully")
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration {migration_id} failed: {e}")
            raise
    
    def rollback_migration(self, migration_id: str) -> bool:
        """Rollback a specific migration."""
        try:
            # Find the migration file
            available = self._get_available_migrations()
            migration = next((m for m in available if m['migration_id'] == migration_id), None)
            
            if not migration:
                print(f"❌ Migration {migration_id} not found")
                return False
            
            if not migration['downgrade']:
                print(f"❌ Migration {migration_id} has no rollback function")
                return False
            
            print(f"🔄 Rolling back migration {migration_id}")
            
            # Execute the downgrade function
            migration['downgrade']()
            
            # Remove from applied migrations
            db.session.execute(text("""
                DELETE FROM schema_migrations WHERE migration_id = :migration_id
            """), {'migration_id': migration_id})
            
            db.session.commit()
            print(f"✅ Migration {migration_id} rolled back successfully")
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Rollback of migration {migration_id} failed: {e}")
            raise
    
    def apply_all_pending(self, dry_run: bool = False) -> bool:
        """Apply all pending migrations."""
        if not dry_run:
            self._backup_database()
        
        # Keep applying migrations until none are pending
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            pending = self.get_pending_migrations()
            
            if not pending:
                print("✅ No pending migrations")
                return True
            
            print(f"Found {len(pending)} pending migration(s)")
            
            # Apply the first pending migration
            migration = pending[0]
            if not self.apply_migration(migration, dry_run):
                return False
            
            iteration += 1
            
            # If dry run, we can't actually change state, so break after first iteration
            if dry_run:
                print(f"[DRY RUN] Would continue applying {len(pending)-1} more migrations...")
                break
        
        if iteration >= max_iterations:
            print(f"⚠️  Stopped after {max_iterations} iterations to prevent infinite loop")
            return False
        
        print(f"{'[DRY RUN] ' if dry_run else ''}✅ All migrations applied successfully")
        return True
    
    def get_migration_status(self) -> Dict:
        """Get comprehensive migration status."""
        self._ensure_migration_table()
        
        applied = self._get_applied_migrations()
        available = self._get_available_migrations()
        pending = self.get_pending_migrations()
        
        return {
            'applied_count': len(applied),
            'available_count': len(available),
            'pending_count': len(pending),
            'applied_migrations': applied,
            'pending_migrations': [m['migration_id'] for m in pending],
            'last_applied': applied[-1] if applied else None
        }
    
    def is_fresh_database(self) -> bool:
        """Check if this is a fresh database (no tables)."""
        try:
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            return len(tables) == 0
        except Exception:
            return True


def create_migration_template(migration_id: str, description: str) -> str:
    """Create a new migration file template."""
    template = f'''#!/usr/bin/env python3
"""
Migration {migration_id}: {description}
Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

import sys
import os

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from models.user import db
from sqlalchemy import text


def upgrade():
    """Apply the migration."""
    print(f"Applying migration {migration_id}: {description}")
    
    # TODO: Add your migration logic here
    # Example:
    # db.session.execute(text("""
    #     ALTER TABLE table_name ADD COLUMN new_column TYPE
    # """))
    # db.session.commit()
    
    pass


def downgrade():
    """Rollback the migration."""
    print(f"Rolling back migration {migration_id}: {description}")
    
    # TODO: Add your rollback logic here
    # Example:
    # db.session.execute(text("""
    #     ALTER TABLE table_name DROP COLUMN new_column
    # """))
    # db.session.commit()
    
    pass


# Migration metadata
MIGRATION_ID = "{migration_id}"
DESCRIPTION = "{description}"
DEPENDENCIES = []  # List of migration IDs that must be applied first


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
'''
    return template
