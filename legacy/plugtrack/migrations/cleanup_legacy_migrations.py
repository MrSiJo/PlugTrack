#!/usr/bin/env python3
"""
Script to organize legacy migration files into legacy/ directory.
Preserves historical scripts while keeping main directory clean.
"""

import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

def ensure_legacy_directory():
    """Ensure the legacy directory exists."""
    migrations_dir = Path(__file__).parent
    legacy_dir = migrations_dir / "legacy"
    legacy_dir.mkdir(exist_ok=True)
    return legacy_dir

def move_legacy_files():
    """Move legacy migration files to legacy/ directory."""
    migrations_dir = Path(__file__).parent
    legacy_dir = ensure_legacy_directory()
    
    legacy_files = [
        'add_baseline_flag.py',
        'add_efficiency_indexes.sql', 
        'add_phase2_indexes.py',
        'add_phase4_fields_and_indexes.py',
        'add_phase5_fields.py',
        'migrate_phase3.py',
        'run_efficiency_indexes.py',
        'seed_phase3_settings.py',
        'seed_phase4_settings.py',
        'setup_phase4.py',
        '005_make_preconditioning_nullable.py',
        'demo_stage53.py',
        'fix_phase5_schema.py',
        'fix_user.py'
    ]
    
    moved = []
    skipped = []
    
    for filename in legacy_files:
        source_path = migrations_dir / filename
        target_path = legacy_dir / filename
        
        if source_path.exists():
            if target_path.exists():
                print(f"⚠️  {filename} already exists in legacy/, skipping")
                skipped.append(filename)
            else:
                shutil.move(str(source_path), str(target_path))
                moved.append(filename)
        else:
            print(f"ℹ️  {filename} not found, skipping")
    
    print(f"📦 Moved {len(moved)} files to legacy/")
    if skipped:
        print(f"⚠️  Skipped {len(skipped)} existing files")
    
    return moved, skipped

def verify_modern_system():
    """Verify the modern migration system is in place."""
    migrations_dir = Path(__file__).parent
    
    required_files = [
        'migration_manager.py',
        'versions/000_migration_system_setup.py',
        'versions/001_initial_schema.py', 
        'versions/002_seed_default_settings.py',
        'versions/003_legacy_preconditioning_fix.py'
    ]
    
    missing = []
    for filename in required_files:
        if not (migrations_dir / filename).exists():
            missing.append(filename)
    
    if missing:
        print(f"❌ Missing required files: {missing}")
        return False
    
    print("✅ Modern migration system files verified")
    return True

def show_directory_structure():
    """Show the organized directory structure after cleanup."""
    migrations_dir = Path(__file__).parent
    
    print("\n📁 Migrations directory structure:")
    
    # Core system files
    core_files = [
        'migration_manager.py',
        'MIGRATION_CLEANUP_PLAN.md',
        'cleanup_legacy_migrations.py'
    ]
    
    # Utility files
    utility_files = [
        'fix_db.py',
        'initialize_baselines.py', 
        'simple_db_test.py'
    ]
    
    # Modern migrations
    versions_dir = migrations_dir / 'versions'
    version_files = []
    if versions_dir.exists():
        version_files = [f.name for f in versions_dir.glob('*.py')]
    
    # Legacy files
    legacy_dir = migrations_dir / 'legacy'
    legacy_files = []
    if legacy_dir.exists():
        legacy_files = [f.name for f in legacy_dir.glob('*')]
    
    print("\n🏗️  Core System:")
    for f in core_files:
        status = "✅" if (migrations_dir / f).exists() else "❌"
        print(f"  {status} {f}")
    
    print("\n🔧 Utility Scripts:")
    for f in utility_files:
        status = "✅" if (migrations_dir / f).exists() else "❌"
        print(f"  {status} {f}")
    
    print("\n📦 versions/ (Modern Migrations):")
    for f in sorted(version_files):
        print(f"  ✅ {f}")
    
    print("\n🗂️  legacy/ (Historical Scripts):")
    for f in sorted(legacy_files):
        print(f"  📜 {f}")
    
    print(f"\n📊 Summary:")
    print(f"  • Core files: {len([f for f in core_files if (migrations_dir / f).exists()])}")
    print(f"  • Utility scripts: {len([f for f in utility_files if (migrations_dir / f).exists()])}")
    print(f"  • Modern migrations: {len(version_files)}")
    print(f"  • Legacy scripts: {len(legacy_files)}")

def main():
    """Main organization function."""
    print("🧹 PlugTrack Migration Organization")
    print("=" * 40)
    
    # Step 1: Verify modern system
    if not verify_modern_system():
        print("❌ Modern migration system not complete. Aborting organization.")
        return False
    
    # Step 2: Show what will be done
    print("\n📋 This script will:")
    print("  1. Create/use migrations/legacy/ directory")
    print("  2. Move superseded legacy files to legacy/") 
    print("  3. Keep utility scripts in main directory")
    print("  4. Keep modern migration system in main directory")
    print("  5. Preserve all historical scripts for reference")
    
    # Step 3: Confirm with user
    response = input("\n⚠️  Proceed with organization? (y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("Organization cancelled.")
        return False
    
    # Step 4: Move legacy files
    moved, skipped = move_legacy_files()
    
    # Step 5: Show results
    print(f"\n🎉 Organization completed!")
    print(f"   Moved to legacy/: {len(moved)} files")
    if skipped:
        print(f"   Already in legacy/: {len(skipped)} files")
    
    # Step 6: Show organized structure
    show_directory_structure()
    
    print(f"\n✅ Migration directory is now organized!")
    print(f"💡 Benefits:")
    print(f"   • Clean main directory with modern system")
    print(f"   • Historical scripts preserved in legacy/")
    print(f"   • Easy to find and reference old migrations")
    print(f"   • Single flask init-db command for users")
    
    print(f"\n🔧 Next steps:")
    print(f"   1. Test: flask migration-status")
    print(f"   2. Test: flask init-db --dry-run")
    print(f"   3. Update documentation if needed")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
