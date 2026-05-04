# Legacy Migration Scripts

This directory contains historical migration scripts that have been superseded by the modern versioned migration system.

## ⚠️ Important Notice

**These scripts are for reference only and should NOT be run manually.**

The functionality of these legacy scripts has been consolidated into the modern migration system located in `../versions/`. Use `flask init-db` instead of running these scripts.

## 📁 Contents

### Phase Migration Scripts
- `migrate_phase3.py` - Phase 3 database changes (session_meta table, venue_type column)
- `add_phase4_fields_and_indexes.py` - Phase 4 schema additions
- `add_phase5_fields.py` - Phase 5 preconditioning fields
- `005_make_preconditioning_nullable.py` - Phase 5.3 nullable preconditioning

### Index and Performance Scripts
- `add_baseline_flag.py` - Baseline session flagging
- `add_phase2_indexes.py` - Performance indexes
- `add_efficiency_indexes.sql` - SQL-only efficiency indexes
- `run_efficiency_indexes.py` - Efficiency calculation indexes

### Settings Scripts
- `seed_phase3_settings.py` - Phase 3 default settings
- `seed_phase4_settings.py` - Phase 4 enhanced settings

### Setup and Utility Scripts
- `setup_phase4.py` - Automated Phase 4 setup
- `demo_stage53.py` - Empty demo file
- `fix_phase5_schema.py` - Empty fix file
- `fix_user.py` - Empty user fix file

## 🔄 Modern Equivalent

Instead of running these legacy scripts, use the modern migration system:

```bash
# Check migration status
flask migration-status

# Initialize database (handles everything automatically)
flask init-db

# Apply only pending migrations
flask apply-migrations
```

## 📚 Historical Context

These scripts represent the evolution of PlugTrack's database schema through different phases:

- **Phase 2**: Basic indexing improvements
- **Phase 3**: Session metadata and venue types
- **Phase 4**: Import/export functionality and performance
- **Phase 5**: Preconditioning tracking and tri-state support

All functionality from these phases has been consolidated into the modern versioned migrations:
- `000_migration_system_setup.py` - Migration framework
- `001_initial_schema.py` - Complete current schema
- `002_seed_default_settings.py` - All default settings
- `003_legacy_preconditioning_fix.py` - Preconditioning nullable fix

## 🛠️ If You Need to Reference Legacy Logic

These files remain available for:
1. Understanding the historical evolution of the schema
2. Debugging migration-related issues
3. Extracting specific SQL patterns for new migrations
4. Documentation and learning purposes

**Never run these scripts directly** - they may conflict with the modern migration system and could cause database corruption.
