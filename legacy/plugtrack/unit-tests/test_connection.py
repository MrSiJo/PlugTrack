#!/usr/bin/env python3
"""
Test database connectivity and table creation
"""

import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def test_db_connection():
    """Test basic database connectivity"""
    try:
        from __init__ import create_app, db
        
        print("🔍 Testing database connection...")
        
        # Create app with test config
        app = create_app()
        
        with app.app_context():
            print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
            
            # Test if we can connect
            try:
                db.engine.connect()
                print("✅ Database connection successful")
            except Exception as e:
                print(f"❌ Database connection failed: {e}")
                return False
            
            # Test if tables exist
            try:
                from models import ChargingSession
                result = db.session.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = result.fetchall()
                print(f"📋 Found tables: {[t[0] for t in tables]}")
                
                if 'charging_session' in [t[0] for t in tables]:
                    print("✅ charging_session table exists")
                    
                    # Check table structure
                    result = db.session.execute("PRAGMA table_info(charging_session);")
                    columns = result.fetchall()
                    print(f"📊 charging_session has {len(columns)} columns:")
                    for col in columns:
                        col_id, col_name, col_type, not_null, default_val, pk = col
                        print(f"  {col_name}: {col_type} {'NOT NULL' if not_null else 'NULL'} {'PK' if pk else ''}")
                else:
                    print("❌ charging_session table not found")
                    return False
                    
            except Exception as e:
                print(f"❌ Error checking tables: {e}")
                return False
            
            return True
            
    except Exception as e:
        print(f"❌ Error in test: {e}")
        return False

if __name__ == '__main__':
    success = test_db_connection()
    if success:
        print("\n✅ Database test passed!")
    else:
        print("\n❌ Database test failed!")
        sys.exit(1)
