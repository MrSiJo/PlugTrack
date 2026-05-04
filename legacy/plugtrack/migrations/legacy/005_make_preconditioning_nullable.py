#!/usr/bin/env python3
"""
Migration: Make preconditioning fields nullable for tri-state support
Created for Phase 5.3 implementation
"""

import sqlite3
import os
import sys
from datetime import datetime

def migrate_preconditioning_nullable(db_path):
    """
    Make preconditioning_used and preconditioning_events nullable.
    SQLite requires recreating the table to modify column constraints.
    """
    
    print(f"🔧 Starting migration: Make preconditioning fields nullable")
    print(f"Database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return False
        
    # Backup the database first
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✅ Database backed up to: {backup_path}")
    except Exception as e:
        print(f"⚠️  Could not create backup: {e}")
        print("Proceeding with migration...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Start transaction
        cursor.execute("BEGIN TRANSACTION;")
        
        # Check current schema
        cursor.execute("PRAGMA table_info(charging_session);")
        columns = cursor.fetchall()
        
        print("📋 Current schema:")
        precon_fields = {}
        for col in columns:
            if 'preconditioning' in col[1]:
                name, col_type, not_null, default_val = col[1], col[2], col[3], col[4]
                precon_fields[name] = {'type': col_type, 'not_null': not_null, 'default': default_val}
                nullable = 'NOT NULL' if not_null else 'NULLABLE'
                print(f"  {name}: {col_type}, {nullable}")
        
        # Check if migration is needed
        needs_migration = any(field['not_null'] for field in precon_fields.values())
        
        if not needs_migration:
            print("✅ Preconditioning fields are already nullable - no migration needed!")
            cursor.execute("ROLLBACK;")
            conn.close()
            return True
        
        print("\n🔄 Creating new table with nullable preconditioning fields...")
        
        # Create new table with correct schema
        create_table_sql = """
        CREATE TABLE charging_session_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            car_id INTEGER NOT NULL,
            date DATE NOT NULL,
            odometer INTEGER NOT NULL,
            charge_type VARCHAR(20) NOT NULL,
            charge_speed_kw FLOAT NOT NULL,
            location_label VARCHAR(200),
            charge_network VARCHAR(100),
            charge_delivered_kwh FLOAT NOT NULL,
            duration_mins INTEGER NOT NULL,
            cost_per_kwh FLOAT,
            soc_from INTEGER NOT NULL,
            soc_to INTEGER NOT NULL,
            notes TEXT,
            venue_type VARCHAR(20),
            is_baseline BOOLEAN DEFAULT 0 NOT NULL,
            ambient_temp_c FLOAT,
            preconditioning_used BOOLEAN,
            preconditioning_events INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user (id),
            FOREIGN KEY (car_id) REFERENCES car (id)
        );
        """
        cursor.execute(create_table_sql)
        
        # Copy data from old table to new table
        print("📦 Copying existing data...")
        cursor.execute("""
            INSERT INTO charging_session_new 
            SELECT id, user_id, car_id, date, odometer, charge_type, charge_speed_kw,
                   location_label, charge_network, charge_delivered_kwh, duration_mins,
                   cost_per_kwh, soc_from, soc_to, notes, venue_type, is_baseline,
                   ambient_temp_c, 
                   CASE 
                       WHEN preconditioning_used = 1 THEN 1
                       WHEN preconditioning_used = 0 THEN 0
                       ELSE NULL
                   END as preconditioning_used,
                   CASE 
                       WHEN preconditioning_events > 0 THEN preconditioning_events
                       ELSE NULL
                   END as preconditioning_events,
                   created_at
            FROM charging_session;
        """)
        
        rows_copied = cursor.rowcount
        print(f"✅ Copied {rows_copied} rows")
        
        # Drop old table and rename new table
        print("🔄 Replacing old table...")
        cursor.execute("DROP TABLE charging_session;")
        cursor.execute("ALTER TABLE charging_session_new RENAME TO charging_session;")
        
        # Recreate indexes (if any existed)
        print("🔍 Recreating indexes...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_charging_session_user_id ON charging_session(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_charging_session_car_id ON charging_session(car_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_charging_session_date ON charging_session(date);")
        
        # Commit transaction
        cursor.execute("COMMIT;")
        
        # Verify the new schema
        cursor.execute("PRAGMA table_info(charging_session);")
        new_columns = cursor.fetchall()
        
        print("\n✅ Migration completed! New schema:")
        for col in new_columns:
            if 'preconditioning' in col[1]:
                name, col_type, not_null, default_val = col[1], col[2], col[3], col[4]
                nullable = 'NOT NULL' if not_null else 'NULLABLE'
                print(f"  {name}: {col_type}, {nullable}")
        
        print(f"\n🎉 Migration successful!")
        print(f"📋 {rows_copied} existing sessions preserved")
        print(f"💾 Backup available at: {backup_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        cursor.execute("ROLLBACK;")
        return False
        
    finally:
        conn.close()

def main():
    """Run the migration"""
    # Use the same path structure as the app
    db_path = "instance/plugtrack.db"
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    success = migrate_preconditioning_nullable(db_path)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
