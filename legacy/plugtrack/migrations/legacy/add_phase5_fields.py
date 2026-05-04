#!/usr/bin/env python3
"""
Database migration script for PlugTrack Phase 5.1.
Adds new fields to charging_session table:
- preconditioning_used (boolean)
- preconditioning_events (integer)
- ambient_temp_c (float, if not already present)
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

def add_phase5_fields():
    """Add Phase 5.1 database fields"""
    app = create_app()
    
    with app.app_context():
        try:
            print("Adding Phase 5.1 database fields...")
            
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
            
            # Add preconditioning_used column
            try:
                db.session.execute(text("""
                    ALTER TABLE charging_session 
                    ADD COLUMN preconditioning_used BOOLEAN DEFAULT FALSE NOT NULL
                """))
                print("✓ Added preconditioning_used column to charging_session")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print("ℹ preconditioning_used column already exists")
                else:
                    print(f"⚠ preconditioning_used column error: {e}")
            
            # Add preconditioning_events column
            try:
                db.session.execute(text("""
                    ALTER TABLE charging_session 
                    ADD COLUMN preconditioning_events INTEGER DEFAULT 0 NOT NULL
                """))
                print("✓ Added preconditioning_events column to charging_session")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print("ℹ preconditioning_events column already exists")
                else:
                    print(f"⚠ preconditioning_events column error: {e}")
            
            db.session.commit()
            print("\n✅ All Phase 5.1 fields added successfully!")
            
        except Exception as e:
            print(f"❌ Error adding Phase 5.1 fields: {e}")
            db.session.rollback()
            raise

if __name__ == "__main__":
    add_phase5_fields()
