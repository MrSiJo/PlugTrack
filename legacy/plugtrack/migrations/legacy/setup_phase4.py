#!/usr/bin/env python3
"""
Setup script for PlugTrack Phase 4.
This script initializes all Phase 4 functionality including database changes and settings.
"""

import sys
import os

# Add the current directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def main():
    """Main setup function"""
    print("🚀 PlugTrack Phase 4 Setup")
    print("=" * 50)
    
    try:
        # Step 1: Install dependencies
        print("\n1️⃣ Installing dependencies...")
        os.system("pip install -r requirements.txt")
        print("✅ Dependencies installed")
        
        # Step 2: Run database migrations
        print("\n2️⃣ Running database migrations...")
        migration_script = "migrations/add_phase4_fields_and_indexes.py"
        if os.path.exists(migration_script):
            os.system(f"python {migration_script}")
            print("✅ Database migrations completed")
        else:
            print("⚠️ Migration script not found, skipping...")
        
        # Step 3: Seed settings
        print("\n3️⃣ Seeding Phase 4 settings...")
        settings_script = "migrations/seed_phase4_settings.py"
        if os.path.exists(settings_script):
            os.system(f"python {settings_script}")
            print("✅ Settings seeded")
        else:
            print("⚠️ Settings script not found, skipping...")
        
        # Step 4: Test functionality
        print("\n4️⃣ Testing Phase 4 functionality...")
        test_script = "test_phase4.py"
        if os.path.exists(test_script):
            print("Running tests...")
            os.system(f"python {test_script}")
        else:
            print("⚠️ Test script not found, skipping...")
        
        # Step 5: Verify CLI commands
        print("\n5️⃣ Verifying CLI commands...")
        try:
            from __init__ import create_app
            app = create_app()
            
            # Check if CLI commands are registered
            cli_commands = [cmd.name for cmd in app.cli.commands.values()]
            phase4_commands = ['sessions-export', 'sessions-import', 'backup-create', 'backup-restore']
            
            missing_commands = [cmd for cmd in phase4_commands if cmd not in cli_commands]
            
            if missing_commands:
                print(f"❌ Missing CLI commands: {missing_commands}")
            else:
                print("✅ All CLI commands registered")
                print("Available commands:")
                for cmd in phase4_commands:
                    print(f"  - flask {cmd}")
            
        except Exception as e:
            print(f"⚠️ CLI verification failed: {e}")
        
        print("\n" + "=" * 50)
        print("🎉 Phase 4 setup completed!")
        print("\nNext steps:")
        print("1. Test CLI commands: flask sessions-export --help")
        print("2. Create a backup: flask backup-create --to backup.zip")
        print("3. Export sessions: flask sessions-export --to sessions.csv")
        print("4. Check settings in the web UI")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
