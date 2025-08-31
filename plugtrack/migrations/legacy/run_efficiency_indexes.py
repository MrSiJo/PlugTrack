#!/usr/bin/env python3
"""
Migration script to add efficiency calculation indexes.
Run this to add the recommended database indexes for better performance.
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

def run_efficiency_indexes_migration():
    """Add efficiency calculation indexes to the database."""
    print("Starting efficiency indexes migration...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            print("Adding efficiency calculation indexes...")
            
            # SQL statements to create indexes (properly wrapped with text())
            index_statements = [
                text("CREATE INDEX IF NOT EXISTS idx_cs_user_car_date_id ON charging_session(user_id, car_id, date, id)"),
                text("CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo ON charging_session(user_id, car_id, odometer)")
            ]
            
            for i, statement in enumerate(index_statements, 1):
                try:
                    db.session.execute(statement)
                    print(f"✓ Index {i} created successfully")
                except Exception as e:
                    print(f"⚠ Index {i} creation: {e}")
                    # Continue with other indexes even if one fails
            
            # Commit all changes
            db.session.commit()
            print("✓ Efficiency indexes migration completed!")
            
    except Exception as e:
        print(f"Error during migration: {e}")
        print("Migration failed!")
        return False
    
    return True

if __name__ == "__main__":
    success = run_efficiency_indexes_migration()
    sys.exit(0 if success else 1)
