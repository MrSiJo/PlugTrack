#!/usr/bin/env python3
"""
Migration 008: Baseline P1-P5 Squashed (Phase 7 B7-3)
Created: 2024-12-21 Consolidates all P1-P5 functionality into a single baseline migration
"""

import sys
import os

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from models.user import db
from models.settings import Settings
from models.user import User
from sqlalchemy import text, inspect


def upgrade():
    """Apply the baseline P1-P5 squashed migration."""
    print("Applying migration 008: Baseline P1-P5 Squashed")
    
    # Check if this is a fresh database
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    
    if len(tables) == 0:
        print("  Fresh database detected - applying complete baseline schema")
        _create_complete_baseline_schema()
        _seed_baseline_settings()
    else:
        print("  Existing database detected - marking P1-P5 migrations as applied")
        _mark_p1_p5_as_applied()
    
    db.session.commit()
    print("✅ Baseline P1-P5 squashed migration completed")


def _create_complete_baseline_schema():
    """Create the complete baseline schema for P1-P5."""
    print("  Creating complete baseline schema...")
    
    # Create schema_migrations table first
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_id VARCHAR(10) NOT NULL UNIQUE,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rollback_sql TEXT
        )
    """))
    
    # Create users table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(80) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # Create cars table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS car (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            make VARCHAR(100) NOT NULL,
            model VARCHAR(100) NOT NULL,
            battery_kwh FLOAT NOT NULL,
            efficiency_mpkwh FLOAT,
            active BOOLEAN DEFAULT 1,
            recommended_full_charge_enabled BOOLEAN DEFAULT 0,
            recommended_full_charge_frequency_value INTEGER,
            recommended_full_charge_frequency_unit VARCHAR(10),
            FOREIGN KEY (user_id) REFERENCES user(id)
        )
    """))
    
    # Create charging_session table with all P1-P5 fields
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS charging_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            car_id INTEGER NOT NULL,
            date DATE NOT NULL,
            odometer INTEGER NOT NULL,
            charge_type VARCHAR(10) NOT NULL,
            charge_speed_kw FLOAT NOT NULL,
            location_label VARCHAR(200) NOT NULL,
            charge_network VARCHAR(100),
            charge_delivered_kwh FLOAT NOT NULL,
            duration_mins INTEGER NOT NULL,
            cost_per_kwh FLOAT NOT NULL,
            soc_from INTEGER NOT NULL,
            soc_to INTEGER NOT NULL,
            notes TEXT,
            venue_type VARCHAR(20),
            is_baseline BOOLEAN DEFAULT 0 NOT NULL,
            ambient_temp_c FLOAT,
            preconditioning_used BOOLEAN,
            preconditioning_events INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id),
            FOREIGN KEY (car_id) REFERENCES car(id)
        )
    """))
    
    # Create session_meta table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS session_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES charging_session(id) ON DELETE CASCADE,
            UNIQUE(session_id, key)
        )
    """))
    
    # Create settings table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            key VARCHAR(100) NOT NULL,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id),
            UNIQUE(user_id, key)
        )
    """))
    
    # Create all baseline indexes
    _create_baseline_indexes()
    
    print("    ✓ Complete baseline schema created")


def _create_baseline_indexes():
    """Create all baseline indexes for P1-P5."""
    indexes = [
        # Core indexes
        "CREATE INDEX IF NOT EXISTS idx_car_user ON car(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_user ON charging_session(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_car ON charging_session(car_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_date ON charging_session(date)",
        "CREATE INDEX IF NOT EXISTS idx_cs_user_car ON charging_session(user_id, car_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo ON charging_session(user_id, car_id, odometer)",
        "CREATE INDEX IF NOT EXISTS idx_session_meta_session ON session_meta(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_settings_user ON settings(user_id)",
        
        # Phase 2 indexes
        "CREATE INDEX IF NOT EXISTS idx_sessions_network ON charging_session(charge_network)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_type ON charging_session(charge_type)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user_date ON charging_session(user_id, date DESC)",
        
        # Phase 4 indexes
        "CREATE INDEX IF NOT EXISTS idx_cs_dupe_key ON charging_session(user_id, car_id, date, odometer, charge_delivered_kwh)",
        "CREATE INDEX IF NOT EXISTS idx_settings_user_key ON settings(user_id, key)",
        "CREATE INDEX IF NOT EXISTS idx_cars_user_make_model ON car(user_id, make, model)"
    ]
    
    for index_sql in indexes:
        db.session.execute(text(index_sql))


def _seed_baseline_settings():
    """Seed all baseline settings for P1-P5."""
    print("  Seeding baseline settings...")
    
    # Get all users (should be empty for fresh install)
    users = User.query.all()
    
    # If no users exist, we'll seed settings when the first user is created
    if not users:
        print("    No users found - settings will be seeded during user creation")
        return
    
    # Default settings for all phases P1-P5
    default_settings = {
        'petrol_threshold_p_per_kwh': '52.5',
        'default_efficiency_mpkwh': '4.1',
        'home_aliases_csv': 'home,house,garage',
        'home_charging_speed_kw': '2.3',
        'petrol_price_p_per_litre': '128.9',
        'petrol_mpg': '60.0',
        'allow_efficiency_fallback': '1',
        'show_savings_cards': '1'
    }
    
    for user in users:
        print(f"    Setting up baseline settings for user: {user.username}")
        
        for key, value in default_settings.items():
            # Only add if setting doesn't exist
            existing = Settings.query.filter_by(user_id=user.id, key=key).first()
            if not existing:
                setting = Settings(user_id=user.id, key=key, value=value)
                db.session.add(setting)
                print(f"      ✓ Added {key}: {value}")
            else:
                print(f"      - Exists {key}: {existing.value}")


def _mark_p1_p5_as_applied():
    """Mark P1-P5 migrations as applied for existing databases."""
    print("  Marking P1-P5 migrations as applied...")
    
    # Mark all P1-P5 migrations as applied
    p1_p5_migrations = [
        ('001', 'Initial PlugTrack schema with all current tables and indexes'),
        ('002', 'Seed default settings for all users'),
        ('003', 'Make preconditioning fields nullable for tri-state support'),
        ('004', 'Phase 6 Backend - Stages A & B (Analytics aggregation API endpoints)'),
        ('005', 'Phase 6 Stage C - Achievements & Gamification table and system'),
        ('006', 'Add display settings for savings cards'),
        ('007', 'Add computed fields to charging_session (Phase 7 B7-2)')
    ]
    
    for migration_id, description in p1_p5_migrations:
        try:
            db.session.execute(text("""
                INSERT OR IGNORE INTO schema_migrations (migration_id, description)
                VALUES (:migration_id, :description)
            """), {
                'migration_id': migration_id,
                'description': description
            })
            print(f"    ✓ Marked migration {migration_id} as applied")
        except Exception as e:
            print(f"    ⚠ Error marking migration {migration_id}: {e}")


def downgrade():
    """Rollback the baseline P1-P5 squashed migration."""
    print("Rolling back migration 008: Baseline P1-P5 Squashed")
    
    # This is a complex rollback - better to restore from backup
    print("⚠️  Manual rollback required - this migration consolidates multiple phases")
    print("    To rollback: restore from backup or manually revert to individual migrations")
    
    # Note: Could implement full rollback if needed, but it's complex and risky
    # Better to use database backups for this type of rollback


# Migration metadata
MIGRATION_ID = "008"
DESCRIPTION = "Baseline P1-P5 Squashed - Consolidates all P1-P5 functionality into single baseline"
DEPENDENCIES = []  # This is the new baseline, no dependencies


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
