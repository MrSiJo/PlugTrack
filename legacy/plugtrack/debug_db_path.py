#!/usr/bin/env python3
"""
Debug script to see exactly what database path SQLAlchemy is using
"""

import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def debug_db_path():
    """Debug the database path that SQLAlchemy is trying to use"""
    try:
        from __init__ import create_app, db
        
        print("🔍 Debugging database path...")
        
        # Create app
        app = create_app()
        
        with app.app_context():
            db_uri = app.config['SQLALCHEMY_DATABASE_URI']
            print(f"1. Database URI from config: {db_uri}")
            
            # Check if it's using the environment variable
            env_db_url = os.environ.get('DATABASE_URL')
            print(f"2. Environment DATABASE_URL: {env_db_url}")
            
            # Try to get the engine info
            print(f"3. Database engine: {db.engine}")
            print(f"4. Engine URL: {db.engine.url}")
            print(f"5. Engine name: {db.engine.name}")
            
            # Try to resolve the path
            if db_uri.startswith('sqlite:///'):
                db_path = db_uri.replace('sqlite:///', '')
                print(f"6. Extracted path: {db_path}")
                
                # Check if it's absolute or relative
                if os.path.isabs(db_path):
                    print(f"7. Path is absolute: {db_path}")
                else:
                    print(f"7. Path is relative, resolving...")
                    resolved_path = os.path.abspath(db_path)
                    print(f"   Resolved to: {resolved_path}")
                    
                    # Check if directory exists
                    db_dir = os.path.dirname(resolved_path)
                    if os.path.exists(db_dir):
                        print(f"8. Directory exists: {db_dir}")
                    else:
                        print(f"8. Directory does not exist: {db_dir}")
                        print(f"   Creating directory...")
                        os.makedirs(db_dir, exist_ok=True)
                        print(f"   Directory created: {db_dir}")
                    
                    # Check if file exists
                    if os.path.exists(resolved_path):
                        size = os.path.getsize(resolved_path)
                        print(f"9. File exists: {resolved_path} ({size} bytes)")
                    else:
                        print(f"9. File does not exist: {resolved_path}")
                        
                        # Try to create a simple SQLite file
                        print(f"   Creating test SQLite file...")
                        import sqlite3
                        conn = sqlite3.connect(resolved_path)
                        conn.close()
                        print(f"   Test file created successfully!")
                        
                        # Check file size
                        if os.path.exists(resolved_path):
                            size = os.path.getsize(resolved_path)
                            print(f"   File size after creation: {size} bytes")
                        else:
                            print(f"   File still does not exist after creation!")
            else:
                print(f"6. Unexpected database URI format: {db_uri}")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    debug_db_path()
