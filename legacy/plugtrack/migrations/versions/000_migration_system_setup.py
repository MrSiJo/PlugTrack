#!/usr/bin/env python3
"""
Migration 000: Migration system setup
Created: 2024-12-21 Sets up the migration tracking system
"""

import sys
import os

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from models.user import db
from sqlalchemy import text, inspect


def upgrade():
    """Set up the migration tracking system."""
    print("Applying migration 000: Migration system setup")
    
    # Create the schema_migrations table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_id VARCHAR(10) NOT NULL UNIQUE,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rollback_sql TEXT
        )
    """))
    
    # Check if this is an existing database with data
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    
    has_data = False
    if 'charging_session' in tables:
        result = db.session.execute(text("SELECT COUNT(*) FROM charging_session"))
        count = result.scalar()
        has_data = count > 0
    
    # If this is an existing database with data, mark initial migrations as applied
    if has_data:
        print("  Existing database detected - marking initial migrations as applied")
        
        # Mark initial schema as applied (since it exists)
        try:
            db.session.execute(text("""
                INSERT OR IGNORE INTO schema_migrations (migration_id, description)
                VALUES ('001', 'Initial PlugTrack schema with all current tables and indexes')
            """))
            print("    ✓ Marked migration 001 as applied")
        except Exception as e:
            print(f"    ⚠ Error marking migration 001: {e}")
        
        # Mark settings migration as applied if settings exist
        if 'settings' in tables:
            result = db.session.execute(text("SELECT COUNT(*) FROM settings"))
            settings_count = result.scalar()
            if settings_count > 0:
                try:
                    db.session.execute(text("""
                        INSERT OR IGNORE INTO schema_migrations (migration_id, description)
                        VALUES ('002', 'Seed default settings for all users')
                    """))
                    print("    ✓ Marked migration 002 as applied")
                except Exception as e:
                    print(f"    ⚠ Error marking migration 002: {e}")
    
    db.session.commit()
    print("✅ Migration system setup completed")


def downgrade():
    """Remove the migration tracking system."""
    print("Rolling back migration 000: Migration system setup")
    
    db.session.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    db.session.commit()
    
    print("✅ Migration system setup rolled back")


# Migration metadata
MIGRATION_ID = "000"
DESCRIPTION = "Migration system setup and existing database detection"
DEPENDENCIES = []


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
