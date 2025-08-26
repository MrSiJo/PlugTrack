# Phase 4 — Data Ops & Settings (CLI Import/Export + Backup/Restore)

> **Scope change:** PWA & Docker are deferred to Phase 5.  
> Phase 4 focuses on robust **CLI tooling** (as groundwork for a future UI flow), **backup/restore**, and **settings surfacing**. All logic sits in **services** so the UI can call it later with zero refactor.

---

## Objectives

- **CLI Import/Export (CSV)** for **Charging Sessions** (idempotent, validated, re-importable).
- **Backup/Restore (ZIP)** for **Sessions + Cars + Settings** with dry-run, merge/replace modes.
- **Settings surfaced & seeded** (see list below).
- **Service-layer design** so a future UI just wraps these services (no logic duplication).
- Optional: **minimal dev Docker scaffolding** (no prod container yet).

---

## Architecture (so UI “just works” later)

```
[ CLI (Click) ]         [ Future HTTP API / UI ]
        │                          │
        └─────────▶ [ Services Layer ]  ◀────────┘
                          │
                     [ Models / DB ]
```

### Services (new)
Create **framework-agnostic** services:

```python
# services/io_sessions.py
class SessionIOService:
    @staticmethod
    def export_sessions(user_id: int, dst_path: str,
                        car_id: int | None = None,
                        date_from: "date | None" = None,
                        date_to: "date | None" = None) -> dict:
        # Write CSV, return report: { rows_written, path }

    @staticmethod
    def import_sessions(user_id: int, src_path: str,
                        car_id: int | None = None,
                        dry_run: bool = False,
                        assume_currency: str = "GBP") -> dict:
        # Validate & (optionally) write; return report: { ok, inserted, skipped_duplicates, errors: [...] }
```

```python
# services/io_backup.py
class BackupService:
    @staticmethod
    def create_backup(user_id: int, dst_zip: str) -> dict:
        # Create ZIP with sessions.csv, cars.csv, settings.json, manifest.json, schema_version.txt

    @staticmethod
    def restore_backup(user_id: int, src_zip: str,
                       mode: str = "merge",
                       dry_run: bool = False) -> dict:
        # Validate & restore; merge|replace; returns {ok, imported, skipped, errors: [...]}
```

Shared validation/report types:

```python
# services/validators.py
class ImportReport:
    ok_rows: int
    inserted: int
    skipped_duplicates: int
    errors: list[dict]   # {row, field, message}
    warnings: list[dict]
    def to_cli_text(self) -> str: ...
    def to_json(self) -> dict: ...
```

---

## CLI Commands (thin wrappers around services)

Register in `plugtrack/cli.py`, then `register_cli(app)` in the app factory.

### Sessions Import/Export

```bash
# Export sessions to CSV (round-trip compatible)
flask sessions-export --to /path/file.csv [--car 1] [--from 2025-08-01] [--to 2025-08-31]

# Import sessions from CSV
flask sessions-import --from /path/file.csv [--car 1] [--dry-run]
```

- **CSV header (required)**

```
date,odometer,charge_type,charge_power_kw,location_label,charge_network,charge_delivered_kwh,duration_mins,cost_per_kwh,total_cost_gbp,soc_from,soc_to,ambient_temp_c,notes
```

- **Rules**
  - `date` (YYYY-MM-DD), `odometer` (int), `charge_type` (AC|DC), `charge_delivered_kwh` (float ≥0) are required.
  - `total_cost_gbp` auto-computed if blank and `cost_per_kwh` present.
  - `is_home_charging` inferred via `home_aliases_csv` against `location_label`.
  - **Idempotency key** to avoid dupes:
    `(user_id, car_id, date, odometer, charge_delivered_kwh)`
  - **Dry-run**: validate & report; no writes.
  - On write: enforce **auto-baseline** reassignment for the car.

### Backup/Restore (ZIP)

```bash
# Create full backup (Sessions + Cars + Settings)
flask backup-create  --to /path/backup_YYYYMMDD.zip

# Restore from backup
flask backup-restore --from /path/backup.zip [--mode merge|replace] [--dry-run]
```

- **ZIP layout**
  ```
  /manifest.json
  /schema_version.txt
  /sessions.csv
  /cars.csv
  /settings.json
  ```
- **Manifest example**
  ```json
  {
    "app": "PlugTrack",
    "version": "4.0",
    "created_at": "2025-08-25T12:34:56Z",
    "user_id": 1,
    "counts": {"cars": 1, "sessions": 257, "settings": 12}
  }
  ```
- **Modes**
  - `merge` (default): upsert cars (natural key: name+make+model), upsert settings by key, import sessions with dupe skip.
  - `replace`: auto-backup current DB first, then wipe & restore.

---

## File Formats (UI-friendly & stable)

- **Sessions CSV**: exactly the schema above; export produces the same headers so a round-trip works.
- **Cars CSV** (backup only; header)
  ```
  id,name,make,model,battery_kwh,efficiency_mpkwh,recommended_full_charge_enabled,recommended_full_charge_frequency_value,recommended_full_charge_frequency_unit,notes
  ```
- **Settings JSON**: `{ key: value }` (keep encrypted values encrypted at rest).
- **Schema Versioning**: bump `schema_version.txt` on DB changes; map older versions in service.

---

## Settings — Seed & Surface

Ensure these defaults exist (idempotent seed) **and** are editable in Settings UI:

```python
default_settings = {
  'default_efficiency_mpkwh': '4.1',
  'home_aliases_csv': 'home,house,garage',
  'home_charging_speed_kw': '2.3',
  'petrol_price_p_per_litre': '128.9',
  'petrol_mpg': '60.0',
  'allow_efficiency_fallback': '1',
}
```

**Settings tabs:**
- **Efficiency**
  - `default_efficiency_mpkwh` (number, step 0.1)
- **Home Detection**
  - `home_aliases_csv` (comma-separated chips)
  - `home_charging_speed_kw` (number)
- **Petrol Baseline**
  - `petrol_price_p_per_litre` (p/L)
  - `petrol_mpg` (UK MPG)
  - Read-only preview of petrol **p/kWh** equivalence and **p/mi** threshold used in comparisons
- **Advanced**
  - `allow_efficiency_fallback` (toggle)

---

## Indices & Performance

Add/ensure these indices (migrations):

```sql
-- anchor lookups & pagination
CREATE INDEX IF NOT EXISTS idx_cs_user_car_date_id
  ON charging_session(user_id, car_id, date, id);

-- odometer anchor scans
CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo
  ON charging_session(user_id, car_id, odometer);

-- duplicate detection for import
CREATE INDEX IF NOT EXISTS idx_cs_dupe_key
  ON charging_session(user_id, car_id, date, odometer, charge_delivered_kwh);
```

---

## Error Handling & Reports

- **CLI exit codes**: non-zero on validation failure.
- **Dry-run reports**: print summary table; also write `*.err.csv` alongside source with row-level errors.
- **Logging**: structured logs to stdout (INFO): counts of inserted/skipped/errors.

---

## Minimal Dev Docker (optional, not full containerisation)

For local testing only (no nginx/gunicorn), add:

- `Dockerfile.dev` (python-slim, install deps, run dev server)
- `docker-compose.dev.yml`:
  - Mount code
  - Persist `./data:/app/data`
  - Command: `flask --app plugtrack run -h 0.0.0.0 -p 8000`

This gives you a clean sandbox to test import/export/backup flows.

---

## Tests (quick, high value)

- `test_sessions_roundtrip`: export → drop → import → equal counts.
- `test_sessions_dedup`: import same CSV twice → second run all duplicates.
- `test_backup_modes`: `merge` vs `replace` (replace creates auto-backup).
- `test_settings_seed`: keys seeded and editable.

---

## Acceptance Criteria

- `flask sessions-export` produces a CSV that re-imports without schema edits.
- `flask sessions-import --dry-run` validates and reports; `--dry-run` makes **no DB writes**.
- `flask sessions-import` is **idempotent** (duplicate rows skipped), and **auto-baseline** still works per car.
- `flask backup-create` writes a ZIP with `manifest.json`, `schema_version.txt`, `sessions.csv`, `cars.csv`, `settings.json`.
- `flask backup-restore --dry-run` simulates; `--mode merge|replace` behaves as specified.
- All listed settings appear in the Settings UI and influence analytics/petrol comparisons.

---

## Notes / Constraints

- Keep services **pure** and **stateless** (DB via session), so the future UI can call them as-is.
- Don’t change existing analytics logic in Phase 4; only ensure import/export/backup don’t break baseline or dynamic efficiency behaviour.
- Encrypted settings **remain encrypted** at rest throughout backup/restore.
