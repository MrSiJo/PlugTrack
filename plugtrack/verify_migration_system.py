#!/usr/bin/env python3
"""
Verification script for the new PlugTrack migration system.
Run this to test that the migration framework is working correctly.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)


def test_migration_system():
    """Test the migration system with a temporary database."""
    print("🧪 Testing PlugTrack Migration System")
    print("=" * 40)
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db = os.path.join(temp_dir, "test.db")
        
        # Set up test environment
        os.environ['DATABASE_URL'] = f'sqlite:///{temp_db}'
        
        try:
            from __init__ import create_app
            from migrations.migration_manager import MigrationManager
            
            app = create_app()
            app.config['DATABASE_URL'] = f'sqlite:///{temp_db}'
            
            with app.app_context():
                migration_manager = MigrationManager(app)
                
                # Test 1: Check fresh database detection
                print("1️⃣ Testing fresh database detection...")
                is_fresh = migration_manager.is_fresh_database()
                print(f"   Fresh database: {is_fresh}")
                assert is_fresh, "Should detect fresh database"
                print("   ✅ Fresh database detection works")
                
                # Test 2: Check available migrations
                print("\n2️⃣ Testing migration discovery...")
                available = migration_manager._get_available_migrations()
                print(f"   Found {len(available)} migration(s)")
                for migration in available:
                    print(f"   - {migration['migration_id']}: {migration['description']}")
                assert len(available) >= 3, "Should find at least 3 migrations"
                print("   ✅ Migration discovery works")
                
                # Test 3: Check pending migrations
                print("\n3️⃣ Testing pending migration detection...")
                pending = migration_manager.get_pending_migrations()
                print(f"   Found {len(pending)} pending migration(s)")
                assert len(pending) >= 3, "Should have pending migrations on fresh DB"
                print("   ✅ Pending migration detection works")
                
                # Test 4: Apply migrations (dry run)
                print("\n4️⃣ Testing dry run migration...")
                success = migration_manager.apply_all_pending(dry_run=True)
                assert success, "Dry run should succeed"
                print("   ✅ Dry run migrations work")
                
                # Test 5: Apply actual migrations
                print("\n5️⃣ Testing actual migration application...")
                success = migration_manager.apply_all_pending(dry_run=False)
                assert success, "Migration application should succeed"
                print("   ✅ Migration application works")
                
                # Test 6: Check no pending migrations after application
                print("\n6️⃣ Testing migration state after application...")
                pending_after = migration_manager.get_pending_migrations()
                print(f"   Pending after application: {len(pending_after)}")
                assert len(pending_after) == 0, "Should have no pending migrations after application"
                print("   ✅ Migration state tracking works")
                
                # Test 7: Test status reporting
                print("\n7️⃣ Testing migration status reporting...")
                status = migration_manager.get_migration_status()
                print(f"   Applied: {status['applied_count']}")
                print(f"   Available: {status['available_count']}")
                print(f"   Pending: {status['pending_count']}")
                print(f"   Last applied: {status['last_applied']}")
                assert status['applied_count'] > 0, "Should have applied migrations"
                assert status['pending_count'] == 0, "Should have no pending migrations"
                print("   ✅ Status reporting works")
                
                print(f"\n🎉 All tests passed! Migration system is working correctly.")
                print(f"   Database file: {temp_db}")
                
                return True
                
        except Exception as e:
            print(f"\n❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            # Clean up environment
            if 'DATABASE_URL' in os.environ:
                del os.environ['DATABASE_URL']


def test_init_db_v2():
    """Test the new init_db_v2 system."""
    print("\n🧪 Testing init_db_v2 System")
    print("=" * 30)
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db = os.path.join(temp_dir, "test_init.db")
        
        # Set up test environment
        os.environ['DATABASE_URL'] = f'sqlite:///{temp_db}'
        
        try:
            from init_db_v2 import init_database
            
            # Test dry run first
            print("1️⃣ Testing dry run initialization...")
            success = init_database(dry_run=True, force_fresh=True)
            assert success, "Dry run init should succeed"
            print("   ✅ Dry run initialization works")
            
            # Test actual initialization
            print("\n2️⃣ Testing actual initialization...")
            success = init_database(dry_run=False, force_fresh=True)
            assert success, "Actual init should succeed"
            print("   ✅ Actual initialization works")
            
            # Test incremental initialization (should detect existing data)
            print("\n3️⃣ Testing incremental initialization...")
            success = init_database(dry_run=False, force_fresh=False)
            assert success, "Incremental init should succeed"
            print("   ✅ Incremental initialization works")
            
            print("\n🎉 init_db_v2 tests passed!")
            return True
            
        except Exception as e:
            print(f"\n❌ init_db_v2 test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            # Clean up environment
            if 'DATABASE_URL' in os.environ:
                del os.environ['DATABASE_URL']


if __name__ == '__main__':
    print("🔧 PlugTrack Migration System Verification")
    print("🎯 This script tests the new migration framework")
    print()
    
    # Test migration manager
    success1 = test_migration_system()
    
    # Test init_db_v2
    success2 = test_init_db_v2()
    
    if success1 and success2:
        print("\n🌟 All verification tests passed!")
        print("✅ The migration system is ready for use")
        sys.exit(0)
    else:
        print("\n💥 Some tests failed!")
        print("❌ Please check the migration system setup")
        sys.exit(1)
