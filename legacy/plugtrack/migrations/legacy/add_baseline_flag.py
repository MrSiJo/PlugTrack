#!/usr/bin/env python3
"""
Migration script to add baseline flag and efficiency indexes.
Adds is_baseline column to charging_session table and creates indexes for efficient efficiency calculations.
"""

import sys
import os

# Add the parent directory (plugtrack) to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# Now we can import from the plugtrack package
from __init__ import create_app
from models.charging_session import db
from sqlalchemy import text

def run_baseline_migration():
    """Add baseline flag column and efficiency indexes to the database."""
    print("Starting baseline flag migration...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            print("Adding baseline flag column and efficiency indexes...")
            
            # SQL statements to create indexes and add column
            migration_statements = [
                # Add baseline flag column
                text("ALTER TABLE charging_session ADD COLUMN is_baseline BOOLEAN NOT NULL DEFAULT 0"),
                # Create indexes for efficient efficiency calculations
                text("CREATE INDEX IF NOT EXISTS idx_cs_user_car_date_id ON charging_session(user_id, car_id, date, id)"),
                text("CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo ON charging_session(user_id, car_id, odometer)")
            ]
            
            for i, statement in enumerate(migration_statements, 1):
                try:
                    db.session.execute(statement)
                    print(f"✓ Migration {i} completed successfully")
                except Exception as e:
                    print(f"⚠ Migration {i} failed: {e}")
                    # Continue with other migrations even if one fails
            
            # Commit all changes
            db.session.commit()
            print("✓ Baseline flag migration completed!")
            
    except Exception as e:
        print(f"Error during migration: {e}")
        print("Migration failed!")
        return False
    
    return True

if __name__ == "__main__":
    success = run_baseline_migration()
    sys.exit(0 if success else 1)
