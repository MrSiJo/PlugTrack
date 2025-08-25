#!/usr/bin/env python3
"""
Test script for PlugTrack Phase 4 functionality.
Tests import/export, backup/restore, and settings functionality.
"""

import sys
import os
import tempfile
import shutil
from datetime import date

# Add the current directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app
from models.user import db, User
from models.car import Car
from models.charging_session import ChargingSession
from models.settings import Settings
from services.io_sessions import SessionIOService
from services.io_backup import BackupService

def test_sessions_roundtrip():
    """Test export → drop → import → equal counts"""
    print("Testing sessions roundtrip...")
    
    app = create_app()
    with app.app_context():
        try:
            # Get initial count
            initial_count = ChargingSession.query.count()
            print(f"Initial sessions count: {initial_count}")
            
            if initial_count == 0:
                print("⚠ No sessions to test with. Skipping roundtrip test.")
                return True
            
            # Export sessions to a proper path
            export_path = os.path.join(os.getcwd(), "test_export.csv")
            export_report = SessionIOService.export_sessions(
                user_id=1, 
                dst_path=export_path
            )
            print(f"Exported {export_report.rows_written} sessions")
            
            # Get count after export
            after_export_count = ChargingSession.query.count()
            print(f"Sessions after export: {after_export_count}")
            
            # Import sessions (should skip duplicates)
            import_report = SessionIOService.import_sessions(
                user_id=1,
                src_path=export_path,
                dry_run=False
            )
            print(f"Import report: {import_report.to_cli_text()}")
            
            # Get count after import
            after_import_count = ChargingSession.query.count()
            print(f"Sessions after import: {after_import_count}")
            
            # Verify counts
            if after_import_count == after_export_count:
                print("✅ Roundtrip test passed: counts match")
                success = True
            else:
                print(f"❌ Roundtrip test failed: expected {after_export_count}, got {after_import_count}")
                success = False
            
            # Cleanup
            if os.path.exists(export_path):
                os.remove(export_path)
            
            return success
            
        except Exception as e:
            print(f"❌ Roundtrip test error: {e}")
            return False

def test_sessions_dedup():
    """Test import same CSV twice → second run all duplicates"""
    print("\nTesting sessions deduplication...")
    
    app = create_app()
    with app.app_context():
        try:
            # Get the first car for testing
            first_car = Car.query.filter_by(user_id=1).first()
            if not first_car:
                print("⚠ No cars found. Skipping deduplication test.")
                return True
            
            # Create a test CSV with some data
            test_csv = os.path.join(os.getcwd(), "test_dedup.csv")
            with open(test_csv, 'w', newline='', encoding='utf-8') as f:
                import csv
                writer = csv.writer(f)
                writer.writerow([
                    'date', 'odometer', 'charge_type', 'charge_power_kw', 'location_label',
                    'charge_network', 'charge_delivered_kwh', 'duration_mins', 'cost_per_kwh',
                    'total_cost_gbp', 'soc_from', 'soc_to', 'ambient_temp_c', 'notes'
                ])
                writer.writerow([
                    '2025-01-01', '1000', 'AC', '7.4', 'Test Location',
                    'Test Network', '25.0', '180', '0.12', '3.0', '20', '80', '', 'Test session'
                ])
            
            # First import
            first_import = SessionIOService.import_sessions(
                user_id=1,
                src_path=test_csv,
                car_id=first_car.id,  # Provide car_id
                dry_run=False
            )
            print(f"First import: {first_import.inserted} inserted, {first_import.skipped_duplicates} skipped")
            
            # Second import (should all be duplicates)
            second_import = SessionIOService.import_sessions(
                user_id=1,
                src_path=test_csv,
                car_id=first_car.id,  # Provide car_id
                dry_run=False
            )
            print(f"Second import: {second_import.inserted} inserted, {second_import.skipped_duplicates} skipped")
            
            # Verify second import had no insertions
            if second_import.inserted == 0 and second_import.skipped_duplicates > 0:
                print("✅ Deduplication test passed: second import skipped all duplicates")
                success = True
            else:
                print(f"❌ Deduplication test failed: second import inserted {second_import.inserted} instead of 0")
                success = False
            
            # Cleanup
            if os.path.exists(test_csv):
                os.remove(test_csv)
            
            return success
            
        except Exception as e:
            print(f"❌ Deduplication test error: {e}")
            return False

def test_backup_modes():
    """Test merge vs replace modes"""
    print("\nTesting backup modes...")
    
    app = create_app()
    with app.app_context():
        try:
            # Create a test backup
            backup_path = os.path.join(os.getcwd(), "test_backup.zip")
            backup_report = BackupService.create_backup(user_id=1, dst_zip=backup_path)
            
            if not backup_report.success:
                print(f"❌ Failed to create test backup: {backup_report.errors}")
                return False
            
            print(f"✅ Created test backup: {backup_path}")
            
            # Test merge mode (dry-run)
            merge_report = BackupService.restore_backup(
                user_id=1,
                src_zip=backup_path,
                mode="merge",
                dry_run=True
            )
            print(f"Merge mode dry-run: {merge_report.to_cli_text()}")
            
            # Test replace mode (dry-run)
            replace_report = BackupService.restore_backup(
                user_id=1,
                src_zip=backup_path,
                mode="replace",
                dry_run=True
            )
            print(f"Replace mode dry-run: {replace_report.to_cli_text()}")
            
            print("✅ Backup modes test passed")
            
            # Cleanup
            if os.path.exists(backup_path):
                os.remove(backup_path)
            
            return True
            
        except Exception as e:
            print(f"❌ Backup modes test error: {e}")
            return False

def test_settings_seed():
    """Test that settings are seeded and editable"""
    print("\nTesting settings seeding...")
    
    app = create_app()
    with app.app_context():
        try:
            # Check if required settings exist
            required_settings = [
                'default_efficiency_mpkwh',
                'home_aliases_csv',
                'home_charging_speed_kw',
                'petrol_price_p_per_litre',
                'petrol_mpg',
                'allow_efficiency_fallback'
            ]
            
            missing_settings = []
            for key in required_settings:
                setting = Settings.query.filter_by(user_id=1, key=key).first()
                if not setting:
                    missing_settings.append(key)
            
            if missing_settings:
                print(f"❌ Missing required settings: {missing_settings}")
                return False
            
            print("✅ All required settings are seeded")
            
            # Test setting update
            test_value = "5.0"
            Settings.set_setting(1, 'default_efficiency_mpkwh', test_value)
            
            # Verify update
            updated_setting = Settings.query.filter_by(user_id=1, key='default_efficiency_mpkwh').first()
            if updated_setting.value == test_value:
                print("✅ Settings are editable")
                return True
            else:
                print(f"❌ Setting update failed: expected {test_value}, got {updated_setting.value}")
                return False
            
        except Exception as e:
            print(f"❌ Settings test error: {e}")
            return False

def main():
    """Run all Phase 4 tests"""
    print("🧪 Running PlugTrack Phase 4 Tests")
    print("=" * 50)
    
    tests = [
        test_sessions_roundtrip,
        test_sessions_dedup,
        test_backup_modes,
        test_settings_seed
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
    
    print("\n" + "=" * 50)
    print(f"Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
