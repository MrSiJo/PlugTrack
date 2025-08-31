#!/usr/bin/env python3
"""
Quick fix for migration state after partial failure.
Cleans up the migration tracking table and resets to a clean state.
"""

import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def fix_migration_state():
    """Fix the migration state after partial failure."""
    from __init__ import create_app, db
    from sqlalchemy import text, inspect
    
    app = create_app()
    
    with app.app_context():
        print("🔧 Fixing migration state...")
        
        try:
            # Check current state
            result = db.session.execute(text("SELECT migration_id, description FROM schema_migrations ORDER BY migration_id"))
            applied_migrations = result.fetchall()
            
            print(f"📋 Currently marked as applied:")
            for migration_id, description in applied_migrations:
                print(f"   {migration_id}: {description}")
            
            # Check if database has the expected tables and data
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            expected_tables = ['user', 'car', 'charging_session', 'settings', 'session_meta']
            has_all_tables = all(table in tables for table in expected_tables)
            
            if has_all_tables:
                # Check for data
                result = db.session.execute(text("SELECT COUNT(*) FROM charging_session"))
                session_count = result.scalar()
                
                result = db.session.execute(text("SELECT COUNT(*) FROM user"))
                user_count = result.scalar()
                
                print(f"\n📊 Database state:")
                print(f"   All tables exist: ✅")
                print(f"   Users: {user_count}")
                print(f"   Sessions: {session_count}")
                
                # If we have a working database with data, mark the appropriate migrations as applied
                if session_count > 0 or user_count > 0:
                    print("\n🔄 Resetting migration state for existing database...")
                    
                    # Clear existing migration records
                    db.session.execute(text("DELETE FROM schema_migrations"))
                    
                    # Mark the migrations that should be applied for an existing database
                    migrations_to_apply = [
                        ('000', 'Migration system setup and existing database detection'),
                        ('001', 'Initial PlugTrack schema with all current tables and indexes'),
                        ('002', 'Seed default settings for all users')
                    ]
                    
                    # Check if preconditioning fields are nullable
                    columns = inspector.get_columns('charging_session')
                    precon_fields = [col for col in columns if 'preconditioning' in col['name']]
                    
                    precon_nullable = True
                    for col in precon_fields:
                        if not col.get('nullable', True):
                            precon_nullable = False
                            break
                    
                    if precon_nullable:
                        migrations_to_apply.append(('003', 'Make preconditioning fields nullable for tri-state support'))
                    
                    for migration_id, description in migrations_to_apply:
                        db.session.execute(text("""
                            INSERT INTO schema_migrations (migration_id, description)
                            VALUES (:migration_id, :description)
                        """), {
                            'migration_id': migration_id,
                            'description': description
                        })
                        print(f"   ✅ Marked {migration_id} as applied")
                    
                    db.session.commit()
                    print(f"\n✅ Migration state fixed!")
                    
                else:
                    print("\n⚠️  Database appears empty. Consider using fresh initialization.")
                    # Clear migration table for fresh start
                    db.session.execute(text("DELETE FROM schema_migrations"))
                    db.session.commit()
                    print("   Cleared migration state for fresh start")
            
            else:
                print(f"\n❌ Database is missing expected tables: {[t for t in expected_tables if t not in tables]}")
                return False
            
            # Show final state
            print(f"\n📊 Final migration state:")
            result = db.session.execute(text("SELECT migration_id FROM schema_migrations ORDER BY migration_id"))
            final_migrations = [row[0] for row in result.fetchall()]
            
            if final_migrations:
                print(f"   Applied: {', '.join(final_migrations)}")
            else:
                print(f"   Applied: None (ready for fresh initialization)")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error fixing migration state: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    try:
        success = fix_migration_state()
        print(f"\n💡 Next steps:")
        if success:
            print(f"   1. Run: python migrate.py status")
            print(f"   2. If needed: python migrate.py init")
        else:
            print(f"   1. Check database manually")
            print(f"   2. Consider fresh database setup")
        
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)
