# PlugTrack Phase 4 - Data Ops & Settings

Phase 4 focuses on robust **CLI tooling**, **backup/restore**, and **settings surfacing**. All logic sits in **services** so the UI can call it later with zero refactor.

## 🚀 New Features

### CLI Import/Export (CSV)
- **Export sessions** to CSV with filtering options
- **Import sessions** from CSV with validation and duplicate detection
- **Idempotent** - duplicate rows are automatically skipped
- **Round-trip compatible** - exported CSV can be re-imported without schema edits

### Backup/Restore (ZIP)
- **Full backup** of sessions, cars, settings, and manifest
- **Merge mode** - upsert existing data
- **Replace mode** - auto-backup current data, then wipe & restore
- **Dry-run support** for safe testing

### Settings Management
- **Seeded defaults** for all Phase 4 settings
- **Framework-agnostic services** ready for future UI integration
- **Encrypted values preserved** during backup/restore

## 📋 Requirements

- Python 3.11+
- Flask 3.0.0+
- Click 8.1.7+ (for CLI)
- Existing PlugTrack database

## 🛠️ Installation

1. **Install dependencies:**
   ```bash
   cd plugtrack
   pip install -r requirements.txt
   ```

2. **Run database migrations:**
   ```bash
   python migrations/add_phase4_fields_and_indexes.py
   python migrations/seed_phase4_settings.py
   ```

3. **Verify installation:**
   ```bash
   python test_phase4.py
   ```

## 📖 CLI Usage

### Sessions Export
```bash
# Export all sessions
flask sessions-export --to /path/export.csv

# Export with filters
flask sessions-export --to /path/export.csv --car 1 --from 2025-01-01 --to-date 2025-01-31

# Export for specific user
flask sessions-export --to /path/export.csv --user 2
```

### Sessions Import
```bash
# Import with validation only (dry-run)
flask sessions-import --from /path/import.csv --dry-run

# Import for specific car
flask sessions-import --from /path/import.csv --car 1

# Import for specific user
flask sessions-import --from /path/import.csv --user 2
```

### Backup Operations
```bash
# Create backup
flask backup-create --to /path/backup_20250101.zip

# Restore in merge mode (dry-run)
flask backup-restore --from /path/backup.zip --mode merge --dry-run

# Restore in replace mode
flask backup-restore --from /path/backup.zip --mode replace
```

## 📊 CSV Format

### Sessions CSV Headers
```csv
date,odometer,charge_type,charge_power_kw,location_label,charge_network,charge_delivered_kwh,duration_mins,cost_per_kwh,total_cost_gbp,soc_from,soc_to,ambient_temp_c,notes
```

**Required fields:**
- `date` - YYYY-MM-DD format
- `odometer` - positive integer
- `charge_type` - AC or DC
- `charge_delivered_kwh` - float ≥ 0

**Auto-computed fields:**
- `total_cost_gbp` - calculated from `cost_per_kwh × charge_delivered_kwh` if blank

**Idempotency key:** `(user_id, car_id, date, odometer, charge_delivered_kwh)`

## 🔧 Settings

### Default Values
```python
default_settings = {
    'default_efficiency_mpkwh': '4.1',
    'home_aliases_csv': 'home,house,garage',
    'home_charging_speed_kw': '2.3',
    'petrol_price_p_per_litre': '128.9',
    'petrol_mpg': '60.0',
    'allow_efficiency_fallback': '1'
}
```

### Settings Categories
- **Efficiency** - Default efficiency settings
- **Home Detection** - Home charging aliases and speed
- **Petrol Baseline** - Petrol price and MPG for comparisons
- **Advanced** - Efficiency fallback options

## 🗄️ Database Changes

### New Fields
- `ambient_temp_c` - Optional ambient temperature
- `total_cost_gbp` - Optional explicit total cost

### New Indexes
```sql
-- Anchor lookups & pagination
CREATE INDEX idx_cs_user_car_date_id ON charging_session(user_id, car_id, date, id);

-- Odometer anchor scans
CREATE INDEX idx_cs_user_car_odo ON charging_session(user_id, car_id, odometer);

-- Duplicate detection for import
CREATE INDEX idx_cs_dupe_key ON charging_session(user_id, car_id, date, odometer, charge_delivered_kwh);
```

## 🐳 Development Docker

For local testing (no production containerization):

```bash
# Build and run
docker-compose -f docker-compose.dev.yml up --build

# Or build manually
docker build -f Dockerfile.dev -t plugtrack-dev .
docker run -p 8000:8000 -v $(pwd)/plugtrack:/app plugtrack-dev
```

## 🧪 Testing

Run the comprehensive test suite:

```bash
python test_phase4.py
```

**Test Coverage:**
- ✅ Sessions roundtrip (export → import → equal counts)
- ✅ Sessions deduplication (import same CSV twice)
- ✅ Backup modes (merge vs replace)
- ✅ Settings seeding and editing

## 🔍 Error Handling

### CLI Exit Codes
- `0` - Success
- `1` - Validation failure or error

### Dry-Run Reports
- **Validation errors** printed to console
- **Error CSV** written alongside source file (`*.errors.csv`)
- **Structured logging** with counts and details

### Backup Safety
- **Auto-backup** created before destructive operations
- **Confirmation prompts** for replace mode
- **Schema version validation** for compatibility

## 🏗️ Architecture

```
[ CLI (Click) ]         [ Future HTTP API / UI ]
        │                          │
        └─────────▶ [ Services Layer ]  ◀────────┘
                          │
                     [ Models / DB ]
```

### Services
- **`SessionIOService`** - CSV import/export with validation
- **`BackupService`** - ZIP backup/restore with merge/replace modes
- **`Validators`** - Shared validation and report types

### Future UI Integration
All services are **framework-agnostic** and **stateless**. The future UI can call them directly:

```python
# Example future UI usage
from services.io_sessions import SessionIOService

export_report = SessionIOService.export_sessions(
    user_id=current_user.id,
    dst_path="/tmp/export.csv"
)
```

## 📝 Notes & Constraints

- **Services are pure** - no Flask dependencies, only SQLAlchemy
- **Existing analytics unchanged** - import/export don't break baseline logic
- **Encrypted settings preserved** - remain encrypted at rest
- **Auto-baseline reassignment** - works per car after import
- **Schema versioning** - bump `schema_version.txt` on DB changes

## 🚧 Troubleshooting

### Common Issues

1. **Import validation errors**
   - Check CSV headers match exactly
   - Verify required fields are present
   - Use `--dry-run` to validate before import

2. **Backup restore failures**
   - Ensure ZIP contains all required files
   - Check schema version compatibility
   - Verify user ID exists in target system

3. **CLI command not found**
   - Ensure Click dependency is installed
   - Check Flask app context is available
   - Verify command registration in `run.py`

### Debug Mode
```bash
# Enable debug logging
export FLASK_ENV=development
export FLASK_DEBUG=1

# Run with verbose output
flask --app plugtrack sessions-export --to /tmp/test.csv --verbose
```

## 🔮 Future Enhancements

- **Schema migration** for older backup versions
- **Incremental backups** (delta changes only)
- **Cloud storage integration** (S3, Google Drive)
- **Web UI** for import/export operations
- **Real-time validation** during CSV editing
- **Bulk operations** for multiple files

---

**Phase 4 Status:** ✅ Complete  
**Next Phase:** UI Integration & Advanced Analytics
