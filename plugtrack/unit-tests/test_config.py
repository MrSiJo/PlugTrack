#!/usr/bin/env python3
"""
Test script to verify database configuration
"""

import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def test_config():
    """Test that the database configuration is working correctly"""
    try:
        from __init__ import create_app
        
        print("🔍 Testing database configuration...")
        
        # Create app
        app = create_app()
        
        with app.app_context():
            db_uri = app.config['SQLALCHEMY_DATABASE_URI']
            print(f"Database URI: {db_uri}")
            
            # Check if it's using the environment variable
            env_db_url = os.environ.get('DATABASE_URL')
            if env_db_url:
                print(f"Environment DATABASE_URL: {env_db_url}")
                if env_db_url == db_uri:
                    print("✅ Database URI matches environment variable")
                else:
                    print("❌ Database URI does not match environment variable")
            else:
                print("ℹ No DATABASE_URL environment variable set, using default")
            
            # Check if the path makes sense
            if db_uri.startswith('sqlite:///'):
                db_path = db_uri.replace('sqlite:///', '')
                if not os.path.isabs(db_path):
                    db_path = os.path.abspath(db_path)
                print(f"Database file path: {db_path}")
                
                # Check if the directory exists
                db_dir = os.path.dirname(db_path)
                if os.path.exists(db_dir):
                    print(f"✅ Database directory exists: {db_dir}")
                else:
                    print(f"❌ Database directory does not exist: {db_dir}")
                    
                # Check if the file exists
                if os.path.exists(db_path):
                    size = os.path.getsize(db_path)
                    print(f"✅ Database file exists: {db_path} ({size} bytes)")
                else:
                    print(f"ℹ Database file does not exist yet: {db_path}")
            else:
                print(f"❌ Unexpected database URI format: {db_uri}")
                
    except Exception as e:
        print(f"❌ Error testing configuration: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_config()
