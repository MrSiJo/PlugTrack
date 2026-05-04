#!/usr/bin/env python3
"""
Migration 007: Add computed fields to charging_session (Phase 7 B7-2)
Created: 2024-12-21 Adds precomputed derived metrics columns
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
    """Add computed fields to charging_session table."""
    print("Applying migration 007: Add computed fields to charging_session")
    
    # Check if columns already exist
    inspector = inspect(db.engine)
    columns = inspector.get_columns('charging_session')
    
    existing_columns = {col['name'] for col in columns}
    
    # Fields to add
    computed_fields = [
        ('computed_efficiency_mpkwh', 'REAL'),
        ('computed_pence_per_mile', 'REAL'),
        ('computed_loss_pct', 'REAL')
    ]
    
    fields_to_add = []
    for field_name, field_type in computed_fields:
        if field_name not in existing_columns:
            fields_to_add.append((field_name, field_type))
        else:
            print(f"  ✓ Column {field_name} already exists")
    
    if not fields_to_add:
        print("✅ All computed fields already exist - no migration needed!")
        return
    
    print(f"  Adding {len(fields_to_add)} computed field(s)...")
    
    # Add each field individually (SQLite supports ALTER TABLE ADD COLUMN)
    for field_name, field_type in fields_to_add:
        try:
            db.session.execute(text(f"""
                ALTER TABLE charging_session 
                ADD COLUMN {field_name} {field_type}
            """))
            print(f"    ✓ Added {field_name}")
        except Exception as e:
            print(f"    ⚠ Error adding {field_name}: {e}")
    
    db.session.commit()
    print("✅ Computed fields added successfully")
    
    # Show final schema
    print("\n📋 Updated charging_session schema:")
    inspector = inspect(db.engine)
    columns = inspector.get_columns('charging_session')
    computed_cols = [col for col in columns if 'computed_' in col['name']]
    for col in computed_cols:
        nullable = 'NULL' if col['nullable'] else 'NOT NULL'
        print(f"  {col['name']}: {col['type']} {nullable}")


def downgrade():
    """Remove computed fields from charging_session table."""
    print("Rolling back migration 007: Remove computed fields from charging_session")
    
    # SQLite doesn't support DROP COLUMN, so we need to recreate the table
    print("  SQLite requires table recreation to remove columns...")
    
    # Create new table without computed fields
    db.session.execute(text("""
        CREATE TABLE charging_session_new (
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
    
    # Copy data without computed fields
    print("  Copying existing data...")
    db.session.execute(text("""
        INSERT INTO charging_session_new 
        SELECT id, user_id, car_id, date, odometer, charge_type, charge_speed_kw,
               location_label, charge_network, charge_delivered_kwh, duration_mins,
               cost_per_kwh, soc_from, soc_to, notes, venue_type, is_baseline,
               ambient_temp_c, preconditioning_used, preconditioning_events, created_at
        FROM charging_session
    """))
    
    # Get row count for verification
    result = db.session.execute(text("SELECT COUNT(*) FROM charging_session_new"))
    rows_copied = result.scalar()
    print(f"  ✓ Copied {rows_copied} rows")
    
    # Replace old table
    print("  Replacing old table...")
    db.session.execute(text("DROP TABLE charging_session"))
    db.session.execute(text("ALTER TABLE charging_session_new RENAME TO charging_session"))
    
    # Recreate indexes
    print("  Recreating indexes...")
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
    print(f"✅ Computed fields removed successfully - {rows_copied} sessions preserved")


# Migration metadata
MIGRATION_ID = "007"
DESCRIPTION = "Add computed fields to charging_session (Phase 7 B7-2)"
DEPENDENCIES = ["006"]


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
