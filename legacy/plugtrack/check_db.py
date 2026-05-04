#!/usr/bin/env python3
"""
Simple script to check database structure
"""

import sqlite3
import os

def check_db():
    # Get database path from Flask config
    from __init__ import create_app
    app = create_app()
    
    with app.app_context():
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        if db_uri.startswith('sqlite:///'):
            db_path = db_uri.replace('sqlite:///', '')
            if not os.path.isabs(db_path):
                db_path = os.path.abspath(db_path)
        else:
            print(f"❌ Unexpected database URI format: {db_uri}")
            return
        
        print(f"Checking database at: {db_path}")
        
        if not os.path.exists(db_path):
            print("❌ Database file not found!")
            return
        
        print(f"✅ Database file exists ({os.path.getsize(db_path)} bytes)")
        
        try:
            conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        print(f"\n📋 Tables found ({len(tables)}):")
        for table in tables:
            table_name = table[0]
            print(f"  - {table_name}")
            
            # Get table info
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()
            print(f"    Columns ({len(columns)}):")
            for col in columns:
                col_id, col_name, col_type, not_null, default_val, pk = col
                print(f"      {col_name}: {col_type} {'NOT NULL' if not_null else 'NULL'} {'PK' if pk else ''}")
            print()
        
        # Check if charging_session table has data
        if any('charging_session' in table for table in tables):
            cursor.execute("SELECT COUNT(*) FROM charging_session;")
            count = cursor.fetchone()[0]
            print(f"📊 charging_session table has {count} rows")
            
            if count > 0:
                cursor.execute("SELECT * FROM charging_session LIMIT 1;")
                sample = cursor.fetchone()
                print(f"Sample row: {sample}")
        else:
            print("❌ charging_session table not found!")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error accessing database: {e}")

if __name__ == '__main__':
    check_db()
