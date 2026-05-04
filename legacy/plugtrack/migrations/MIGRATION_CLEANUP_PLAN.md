# Migration Directory Cleanup Plan

## Current State Analysis

The migrations directory contains a mix of legacy scripts and modern versioned migrations. Here's the consolidation plan:

## ✅ Files to KEEP (Modern System)

### Core Framework
- `migration_manager.py` - Migration orchestration framework
- `versions/000_migration_system_setup.py` - Sets up migration tracking
- `versions/001_initial_schema.py` - Complete schema definition
- `versions/002_seed_default_settings.py` - Default settings seeding
- `versions/003_legacy_preconditioning_fix.py` - Preconditioning nullable fix

## 📦 Files to MOVE to legacy/ (Historical/Superseded)

### Superseded by Modern System
- `add_baseline_flag.py` - Functionality in 001_initial_schema.py
- `add_efficiency_indexes.sql` - SQL only, functionality in 001_initial_schema.py  
- `add_phase2_indexes.py` - Functionality in 001_initial_schema.py
- `add_phase4_fields_and_indexes.py` - Functionality in 001_initial_schema.py
- `add_phase5_fields.py` - Functionality in 001_initial_schema.py
- `migrate_phase3.py` - Functionality in 001_initial_schema.py
- `run_efficiency_indexes.py` - Functionality in 001_initial_schema.py
- `seed_phase3_settings.py` - Functionality in 002_seed_default_settings.py
- `seed_phase4_settings.py` - Functionality in 002_seed_default_settings.py
- `setup_phase4.py` - Replaced by modern `flask init-db` command

### Legacy Manual Migration
- `005_make_preconditioning_nullable.py` - Replaced by 003_legacy_preconditioning_fix.py

### Empty/Demo Files
- `demo_stage53.py` - Empty file
- `fix_phase5_schema.py` - Empty file  
- `fix_user.py` - Empty file

## ⚠️ Files to KEEP (Utility/Fix Scripts)

### Useful Troubleshooting Tools
- `fix_db.py` - Complete database recreation utility (useful for emergencies)
- `initialize_baselines.py` - Baseline session initialization (still used)
- `simple_db_test.py` - Database connectivity testing utility
- `verify_migration_system.py` - Migration system testing utility

### Organization Tools
- `cleanup_legacy_migrations.py` - Script to organize legacy files
- `MIGRATION_CLEANUP_PLAN.md` - This documentation file

## 📦 Organization Benefits

After organizing to legacy/ directory:
1. **Clean main directory**: Only active modern migration system visible
2. **Historical preservation**: All legacy scripts kept for reference
3. **Single source of truth**: All schema changes in versioned migrations
4. **Automatic execution**: Users run `flask init-db` instead of multiple scripts
5. **Version tracking**: Know exactly what's been applied
6. **Rollback support**: Safe downgrade capability
7. **Reduced confusion**: Clear separation between old and new systems

## 🚀 Migration Path for Existing Users

1. **Backup current database** (automatic with migration system)
2. **Run `flask init-db`** - Detects existing data and applies only needed migrations
3. **Verify with `flask migration-status`** - Check current state
4. **Clean up legacy files** once confirmed working

## 📋 File Organization Commands

```bash
# Organize legacy migration scripts (run from plugtrack/migrations/)
python cleanup_legacy_migrations.py

# This will create the following structure:
# migrations/
# ├── migration_manager.py              # Core framework
# ├── versions/                        # Modern migrations
# │   ├── 000_migration_system_setup.py
# │   ├── 001_initial_schema.py
# │   ├── 002_seed_default_settings.py
# │   └── 003_legacy_preconditioning_fix.py
# ├── legacy/                          # Historical scripts
# │   ├── add_baseline_flag.py
# │   ├── add_phase2_indexes.py
# │   ├── migrate_phase3.py
# │   └── ... (all legacy files)
# ├── fix_db.py                        # Utility scripts
# ├── initialize_baselines.py
# └── simple_db_test.py
```

## 🔄 What Users Need to Do

### For Fresh Installations
```bash
flask init-db  # One command handles everything
```

### For Existing Installations  
```bash
flask init-db  # Automatically detects existing data and applies only pending migrations
```

### For Verification
```bash
flask migration-status  # Check what's been applied
```

This organization reduces the main migrations directory from **18 files** to **8 active files** (5 modern migrations + 3 utility scripts), while preserving all **14 legacy files** in the `legacy/` subdirectory for historical reference. The system is much cleaner while maintaining complete historical context.
