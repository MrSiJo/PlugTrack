#!/usr/bin/env python3
"""
Convenient migration command runner for PlugTrack
Provides easy access to migration commands without Flask app configuration hassles
"""

import sys
import os

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def show_help():
    """Show available migration commands."""
    print("🔧 PlugTrack Migration Tool")
    print("=" * 30)
    print()
    print("Available commands:")
    print("  status              Show migration status")
    print("  init                Initialize/migrate database")
    print("  init --dry-run      Preview initialization changes")
    print("  init --force-fresh  Force fresh installation")
    print("  create <id> <desc>  Create new migration")
    print("  organize            Organize legacy files")
    print("  test                Test migration system")
    print()
    print("Examples:")
    print("  python migrate.py status")
    print("  python migrate.py init")
    print("  python migrate.py init --dry-run")
    print("  python migrate.py create 004 'Add new feature'")
    print("  python migrate.py organize")

def run_migration_status():
    """Run migration status check."""
    from init_db_v2 import migration_status
    migration_status()

def run_init_database(args):
    """Run database initialization."""
    from init_db_v2 import init_database
    
    dry_run = '--dry-run' in args
    force_fresh = '--force-fresh' in args
    
    success = init_database(dry_run=dry_run, force_fresh=force_fresh)
    return success

def run_create_migration(args):
    """Create a new migration."""
    if len(args) < 3:
        print("❌ Usage: python migrate.py create <migration_id> <description>")
        print("   Example: python migrate.py create 004 'Add new feature'")
        return False
    
    migration_id = args[1]
    description = ' '.join(args[2:])
    
    from init_db_v2 import create_migration
    return create_migration(migration_id, description)

def run_organize_legacy():
    """Organize legacy migration files."""
    try:
        from migrations.cleanup_legacy_migrations import main as cleanup_main
        return cleanup_main()
    except ImportError:
        print("❌ cleanup_legacy_migrations.py not found")
        return False

def run_test_system():
    """Test the migration system."""
    try:
        from verify_migration_system import test_migration_system, test_init_db_v2
        
        print("🧪 Testing Migration System")
        print("=" * 30)
        
        success1 = test_migration_system()
        success2 = test_init_db_v2()
        
        if success1 and success2:
            print("\n🌟 All tests passed!")
            return True
        else:
            print("\n💥 Some tests failed!")
            return False
            
    except ImportError:
        print("❌ verify_migration_system.py not found")
        return False

def main():
    """Main command dispatcher."""
    if len(sys.argv) < 2:
        show_help()
        return True
    
    command = sys.argv[1].lower()
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    
    try:
        if command in ['help', '-h', '--help']:
            show_help()
            return True
        
        elif command == 'status':
            run_migration_status()
            return True
        
        elif command == 'init':
            return run_init_database(args)
        
        elif command == 'create':
            return run_create_migration(args)
        
        elif command == 'organize':
            return run_organize_legacy()
        
        elif command == 'test':
            return run_test_system()
        
        else:
            print(f"❌ Unknown command: {command}")
            show_help()
            return False
            
    except Exception as e:
        print(f"❌ Error running command '{command}': {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
