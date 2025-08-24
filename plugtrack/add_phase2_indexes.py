#!/usr/bin/env python3
"""
Add Phase 2 database indexes for improved performance
Run this script after setting up your database to add the recommended indexes.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from __init__ import create_app
from models.user import db
from sqlalchemy import text

def add_phase2_indexes():
    """Add the recommended indexes for Phase 2"""
    app = create_app()
    
    with app.app_context():
        try:
            # Add indexes for faster filtering
            print("Adding Phase 2 database indexes...")
            
            # Index for date filtering
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_sessions_date 
                ON charging_session(date)
            """))
            print("✓ Added index on charging_session.date")
            
            # Index for car filtering
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_sessions_car 
                ON charging_session(car_id)
            """))
            print("✓ Added index on charging_session.car_id")
            
            # Index for network filtering
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_sessions_network 
                ON charging_session(charge_network)
            """))
            print("✓ Added index on charging_session.charge_network")
            
            # Index for user filtering (should already exist but ensure it)
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_sessions_user 
                ON charging_session(user_id)
            """))
            print("✓ Added index on charging_session.user_id")
            
            # Index for charge type filtering
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_sessions_type 
                ON charging_session(charge_type)
            """))
            print("✓ Added index on charging_session.charge_type")
            
            # Composite index for common queries
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_sessions_user_date 
                ON charging_session(user_id, date DESC)
            """))
            print("✓ Added composite index on charging_session(user_id, date)")
            
            db.session.commit()
            print("\n✅ All Phase 2 indexes added successfully!")
            
        except Exception as e:
            print(f"❌ Error adding indexes: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    add_phase2_indexes()
