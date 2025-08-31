#!/usr/bin/env python3
"""
Migration script for PlugTrack Phase 4.
Adds missing fields and indexes for import/export and backup/restore functionality.
"""

import sys
import os

# Add the parent directory (plugtrack) to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from __init__ import create_app
from models.user import db
from sqlalchemy import text

def add_phase4_fields_and_indexes():
    """Add Phase 4 database fields and indexes"""
    app = create_app()
    
    with app.app_context():
        try:
            print("Adding Phase 4 database fields and indexes...")
            
            # Add missing fields to charging_session table
            # Note: These are optional fields that may not exist in the current schema
            
            # Check if ambient_temp_c column exists, add if not
            try:
                db.session.execute(text("""
                    ALTER TABLE charging_session 
                    ADD COLUMN ambient_temp_c FLOAT
                """))
                print("✓ Added ambient_temp_c column to charging_session")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print("ℹ ambient_temp_c column already exists")
                else:
                    print(f"⚠ ambient_temp_c column error: {e}")
            
            # Check if total_cost_gbp column exists, add if not
            try:
                db.session.execute(text("""
                    ALTER TABLE charging_session 
                    ADD COLUMN total_cost_gbp FLOAT
                """))
                print("✓ Added total_cost_gbp column to charging_session")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print("ℹ total_cost_gbp column already exists")
                else:
                    print(f"⚠ total_cost_gbp column error: {e}")
            
            # Add Phase 4 indexes for performance and duplicate detection
            print("\nAdding Phase 4 indexes...")
            
            # Index for anchor lookups & pagination
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_cs_user_car_date_id
                ON charging_session(user_id, car_id, date, id)
            """))
            print("✓ Added index on charging_session(user_id, car_id, date, id)")
            
            # Index for odometer anchor scans
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo
                ON charging_session(user_id, car_id, odometer)
            """))
            print("✓ Added index on charging_session(user_id, car_id, odometer)")
            
            # Index for duplicate detection during import
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_cs_dupe_key
                ON charging_session(user_id, car_id, date, odometer, charge_delivered_kwh)
            """))
            print("✓ Added index on charging_session(user_id, car_id, date, odometer, charge_delivered_kwh)")
            
            # Note: charge_power_kw field doesn't exist in current model
            # The CSV export/import maps charge_power_kw to charge_speed_kw
            print("ℹ charge_power_kw index not added (field maps to charge_speed_kw)")
            
            # Index for settings lookups
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_settings_user_key
                ON settings(user_id, key)
            """))
            print("✓ Added index on settings(user_id, key)")
            
            # Index for cars lookups
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_cars_user_make_model
                ON car(user_id, make, model)
            """))
            print("✓ Added index on car(user_id, make, model)")
            
            db.session.commit()
            print("\n✅ All Phase 4 fields and indexes added successfully!")
            
        except Exception as e:
            print(f"❌ Error adding Phase 4 fields and indexes: {e}")
            db.session.rollback()
            raise

if __name__ == "__main__":
    add_phase4_fields_and_indexes()
