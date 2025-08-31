#!/usr/bin/env python3
"""
Database migration script for PlugTrack Phase 3.
Creates session_meta table and adds venue_type column to charging_session.
"""

import sys
import os

# Add the parent directory (plugtrack) to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from __init__ import create_app
from models.user import db

def migrate_phase3():
    """Perform Phase 3 database migrations."""
    print("Starting Phase 3 database migration...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            print("Creating session_meta table...")
            
            # Create session_meta table
            create_session_meta_sql = """
            CREATE TABLE IF NOT EXISTS session_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES charging_session(id) ON DELETE CASCADE,
                UNIQUE(session_id, key)
            );
            """
            
            db.session.execute(create_session_meta_sql)
            
            # Create index for performance
            create_index_sql = """
            CREATE INDEX IF NOT EXISTS idx_session_meta_session 
            ON session_meta(session_id);
            """
            
            db.session.execute(create_index_sql)
            
            print("Adding venue_type column to charging_session table...")
            
            # Add venue_type column to charging_session table
            # SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS
            # So we'll check if it exists first
            check_column_sql = """
            SELECT COUNT(*) FROM pragma_table_info('charging_session') 
            WHERE name = 'venue_type';
            """
            
            result = db.session.execute(check_column_sql).fetchone()
            column_exists = result[0] > 0
            
            if not column_exists:
                add_column_sql = """
                ALTER TABLE charging_session 
                ADD COLUMN venue_type TEXT NULL;
                """
                
                db.session.execute(add_column_sql)
                print("✓ Added venue_type column")
            else:
                print("✓ venue_type column already exists")
            
            # Commit all changes
            db.session.commit()
            
            print("✓ Phase 3 migration completed successfully!")
            
    except Exception as e:
        print(f"Error during migration: {e}")
        print("Migration failed!")
        return False
    
    return True

if __name__ == "__main__":
    success = migrate_phase3()
    sys.exit(0 if success else 1)
