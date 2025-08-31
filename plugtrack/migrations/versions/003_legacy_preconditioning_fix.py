#!/usr/bin/env python3
"""
Migration 003: Make preconditioning fields nullable (Phase 5.3)
Created: 2024-12-21 Consolidates 005_make_preconditioning_nullable.py
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
    """Make preconditioning fields nullable for tri-state support."""
    print("Applying migration 003: Make preconditioning fields nullable")
    
    # Check current schema first
    inspector = inspect(db.engine)
    columns = inspector.get_columns('charging_session')
    
    precon_fields = {}
    for col in columns:
        if 'preconditioning' in col['name']:
            precon_fields[col['name']] = {
                'type': str(col['type']),
                'nullable': col['nullable']
            }
    
    print("📋 Current preconditioning schema:")
    for name, info in precon_fields.items():
        nullable_str = 'NULLABLE' if info['nullable'] else 'NOT NULL'
        print(f"  {name}: {info['type']}, {nullable_str}")
    
    # Check if migration is needed
    needs_migration = any(not info['nullable'] for info in precon_fields.values())
    
    if not needs_migration:
        print("✅ Preconditioning fields are already nullable - no migration needed!")
        return
    
    print("\n🔄 Creating new table with nullable preconditioning fields...")
    
    # SQLite requires table recreation for column constraint changes
    # Create new table with correct schema
    db.session.execute(text("""
        CREATE TABLE charging_session_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            car_id INTEGER NOT NULL,
            date DATE NOT NULL,
            odometer INTEGER NOT NULL,
            charge_type VARCHAR(20) NOT NULL,
            charge_speed_kw FLOAT NOT NULL,
            location_label VARCHAR(200),
            charge_network VARCHAR(100),
            charge_delivered_kwh FLOAT NOT NULL,
            duration_mins INTEGER NOT NULL,
            cost_per_kwh FLOAT,
            soc_from INTEGER NOT NULL,
            soc_to INTEGER NOT NULL,
            notes TEXT,
            venue_type VARCHAR(20),
            is_baseline BOOLEAN DEFAULT 0 NOT NULL,
            ambient_temp_c FLOAT,
            preconditioning_used BOOLEAN,
            preconditioning_events INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user (id),
            FOREIGN KEY (car_id) REFERENCES car (id)
        )
    """))
    
    # Copy data with proper NULL handling
    print("📦 Copying existing data...")
    db.session.execute(text("""
        INSERT INTO charging_session_new 
        SELECT id, user_id, car_id, date, odometer, charge_type, charge_speed_kw,
               location_label, charge_network, charge_delivered_kwh, duration_mins,
               cost_per_kwh, soc_from, soc_to, notes, venue_type, is_baseline,
               ambient_temp_c, 
               CASE 
                   WHEN preconditioning_used = 1 THEN 1
                   WHEN preconditioning_used = 0 THEN 0
                   ELSE NULL
               END as preconditioning_used,
               CASE 
                   WHEN preconditioning_events > 0 THEN preconditioning_events
                   ELSE NULL
               END as preconditioning_events,
               created_at
        FROM charging_session
    """))
    
    # Get row count for verification
    result = db.session.execute(text("SELECT COUNT(*) FROM charging_session_new"))
    rows_copied = result.scalar()
    print(f"✅ Copied {rows_copied} rows")
    
    # Replace old table
    print("🔄 Replacing old table...")
    db.session.execute(text("DROP TABLE charging_session"))
    db.session.execute(text("ALTER TABLE charging_session_new RENAME TO charging_session"))
    
    # Recreate indexes
    print("🔍 Recreating indexes...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_cs_user ON charging_session(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_car ON charging_session(car_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_date ON charging_session(date)",
        "CREATE INDEX IF NOT EXISTS idx_cs_user_car ON charging_session(user_id, car_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo ON charging_session(user_id, car_id, odometer)"
    ]
    
    for index_sql in indexes:
        db.session.execute(text(index_sql))
    
    db.session.commit()
    print(f"✅ Migration completed! {rows_copied} sessions preserved with nullable preconditioning fields")


def downgrade():
    """Rollback to non-nullable preconditioning fields."""
    print("Rolling back migration 003: Make preconditioning fields non-nullable")
    
    # This would require reversing the table recreation
    # For safety, we'll just log that this rollback requires manual intervention
    print("⚠️  Manual rollback required - this migration changed column constraints")
    print("    To rollback: restore from backup or recreate table with NOT NULL constraints")
    
    # Note: Could implement full rollback if needed, but it's complex and risky
    # Better to use database backups for this type of rollback


# Migration metadata
MIGRATION_ID = "003"
DESCRIPTION = "Make preconditioning fields nullable for tri-state support"
DEPENDENCIES = ["002"]


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
