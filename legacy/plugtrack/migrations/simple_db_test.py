#!/usr/bin/env python3
"""
Simple test to isolate database connection issue
"""

import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def test_simple_db():
    """Test database connection step by step"""
    try:
        print("🔍 Testing database step by step...")
        
        # Step 1: Check environment
        db_url = os.environ.get('DATABASE_URL')
        print(f"1. Environment DATABASE_URL: {db_url}")
        
        # Step 2: Check if file exists
        if db_url and db_url.startswith('sqlite:///'):
            db_path = db_url.replace('sqlite:///', '')
            if not os.path.isabs(db_path):
                db_path = os.path.abspath(db_path)
            print(f"2. Resolved database path: {db_path}")
            
            if os.path.exists(db_path):
                size = os.path.getsize(db_path)
                print(f"3. Database file exists: {size} bytes")
            else:
                print("3. Database file does not exist")
                
            # Step 3: Try to create a simple SQLite connection
            print("4. Testing direct SQLite connection...")
            import sqlite3
            conn = sqlite3.connect(db_path)
            print("✅ Direct SQLite connection successful!")
            
            # Step 4: Test basic SQLite operations
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT)")
            print("✅ SQLite table creation successful!")
            
            cursor.execute("INSERT INTO test (name) VALUES (?)", ("test_value",))
            print("✅ SQLite insert successful!")
            
            cursor.execute("SELECT * FROM test")
            result = cursor.fetchone()
            print(f"✅ SQLite select successful: {result}")
            
            conn.close()
            print("✅ SQLite connection closed successfully!")
            
        else:
            print("❌ Invalid DATABASE_URL format")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_simple_db()
