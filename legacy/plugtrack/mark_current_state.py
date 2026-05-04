#!/usr/bin/env python3
"""
Script to mark an existing PlugTrack database as being at the current migration state.
Use this when you have a working database that should be considered "up to date".
"""

import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def mark_database_current():
    """Mark the database as being at the current migration state."""
    from __init__ import create_app, db
    from migrations.migration_manager import MigrationManager
    from sqlalchemy import text, inspect
    
    app = create_app()
    
    with app.app_context():
        print("🔍 Analyzing current database state...")
        
        # Check if database has the expected tables
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        expected_tables = ['user', 'car', 'charging_session', 'settings', 'session_meta']
        missing_tables = [table for table in expected_tables if table not in tables]
        
        if missing_tables:
            print(f"❌ Database is missing tables: {missing_tables}")
            print("This doesn't look like a complete PlugTrack database.")
            return False
        
        print("✅ All expected tables found")
        
        # Check if we have data
        result = db.session.execute(text("SELECT COUNT(*) FROM charging_session"))
        session_count = result.scalar()
        
        result = db.session.execute(text("SELECT COUNT(*) FROM user"))
        user_count = result.scalar()
        
        print(f"📊 Database contains:")
        print(f"   Users: {user_count}")
        print(f"   Charging sessions: {session_count}")
        
        if session_count == 0 and user_count == 0:
            print("⚠️  Database appears to be empty. Consider using 'python migrate.py init' instead.")
            return False
        
        # Create migration tracking table
        print("\n🔧 Setting up migration tracking...")
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_id VARCHAR(10) NOT NULL UNIQUE,
                description TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                rollback_sql TEXT
            )
        """))
        
        # Mark all current migrations as applied
        migrations_to_mark = [
            ('000', 'Migration system setup and existing database detection'),
            ('001', 'Initial PlugTrack schema with all current tables and indexes'),
            ('002', 'Seed default settings for all users')
        ]
        
        # Check if we need the preconditioning fix
        columns = inspector.get_columns('charging_session')
        precon_fields = [col for col in columns if 'preconditioning' in col['name']]
        
        needs_precon_fix = False
        for col in precon_fields:
            if not col['nullable']:
                needs_precon_fix = True
                break
        
        if not needs_precon_fix:
            migrations_to_mark.append(('003', 'Make preconditioning fields nullable for tri-state support'))
        
        print(f"\n📝 Marking {len(migrations_to_mark)} migrations as applied:")
        
        for migration_id, description in migrations_to_mark:
            # Check if already marked
            result = db.session.execute(text(
                "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = :id"
            ), {'id': migration_id})
            
            if result.scalar() == 0:
                db.session.execute(text("""
                    INSERT INTO schema_migrations (migration_id, description)
                    VALUES (:migration_id, :description)
                """), {
                    'migration_id': migration_id,
                    'description': description
                })
                print(f"   ✅ Marked migration {migration_id} as applied")
            else:
                print(f"   ℹ️  Migration {migration_id} already marked as applied")
        
        db.session.commit()
        
        print(f"\n🎉 Database marked as current!")
        print(f"💡 You can now use 'python migrate.py status' to see the state")
        
        if needs_precon_fix:
            print(f"\n⚠️  Note: Your database may need migration 003 for preconditioning nullable fix")
            print(f"   Run 'python migrate.py init' to apply any remaining migrations")
        
        return True

if __name__ == "__main__":
    try:
        success = mark_database_current()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
