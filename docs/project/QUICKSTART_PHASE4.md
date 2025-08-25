# 🚀 PlugTrack Phase 4 - Quick Start

Get up and running with Phase 4 in 5 minutes!

## ⚡ Quick Setup

```bash
# 1. Navigate to plugtrack directory
cd plugtrack

# 2. Run the automated setup
python setup_phase4.py

# 3. Verify installation
python test_phase4.py
```

## 🎯 Essential Commands

### Export Your Data
```bash
# Export all charging sessions
flask sessions-export --to my_sessions.csv

# Export with date range
flask sessions-export --to january.csv --from 2025-01-01 --to-date 2025-01-31
```

### Backup Everything
```bash
# Create full backup
flask backup-create --to backup_$(date +%Y%m%d).zip

# Restore from backup (safe mode)
flask backup-restore --from backup.zip --mode merge --dry-run
```

### Import Data
```bash
# Validate CSV before import
flask sessions-import --from new_sessions.csv --dry-run

# Import for specific car
flask sessions-import --from new_sessions.csv --car 1
```

## 📊 CSV Format

Create a CSV with these headers:
```csv
date,odometer,charge_type,charge_power_kw,location_label,charge_network,charge_delivered_kwh,duration_mins,cost_per_kwh,total_cost_gbp,soc_from,soc_to,ambient_temp_c,notes
```

**Example row:**
```csv
2025-01-15,15000,AC,7.4,Home,Home Charger,25.5,180,0.12,3.06,20,80,,Evening charge
```

## 🔧 Key Settings

Phase 4 automatically seeds these settings:
- **Efficiency**: `default_efficiency_mpkwh = 4.1`
- **Home Detection**: `home_aliases_csv = home,house,garage`
- **Charging Speed**: `home_charging_speed_kw = 2.3`
- **Petrol Baseline**: `petrol_price_p_per_litre = 128.9`, `petrol_mpg = 60.0`

## 🧪 Test Everything

```bash
# Run comprehensive tests
python test_phase4.py

# Test individual components
flask sessions-export --to test.csv --dry-run
flask backup-create --to test.zip
```

## 🆘 Need Help?

- **Full Documentation**: See `PHASE4_README.md`
- **CLI Help**: `flask sessions-export --help`
- **Dry-Run First**: Always use `--dry-run` for safe testing
- **Check Logs**: Look for error messages in console output

## 🎉 You're Ready!

Phase 4 is now fully operational. Your data is safe with backup/restore, and you can import/export sessions with confidence!

---

**Next**: Explore the web UI settings or dive into advanced CLI usage patterns.
