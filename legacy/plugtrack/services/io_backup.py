import csv
import json
import os
import zipfile
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from services.validators import ImportReport, BackupReport, ValidationError
from services.io_sessions import SessionIOService

class BackupService:
    """Service for backup and restore operations"""
    
    SCHEMA_VERSION = "4.0"
    APP_NAME = "PlugTrack"
    
    @staticmethod
    def create_backup(user_id: int, dst_zip: str, db_session=None) -> BackupReport:
        """Create a backup ZIP containing sessions, cars, settings, and manifest"""
        try:
            # Use provided session or fall back to global db.session
            session = db_session or db.session
            
            # Create temporary directory for backup files
            temp_dir = Path(dst_zip).parent / f"backup_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            temp_dir.mkdir(exist_ok=True)
            
            # Export sessions
            sessions_csv = temp_dir / "sessions.csv"
            sessions_report = SessionIOService.export_sessions(user_id, str(sessions_csv), db_session=session)
            
            # Export cars
            cars_csv = temp_dir / "cars.csv"
            cars_report = BackupService._export_cars(user_id, str(cars_csv), session)
            
            # Export settings
            settings_json = temp_dir / "settings.json"
            settings_report = BackupService._export_settings(user_id, str(settings_json), session)
            
            # Create manifest
            manifest = BackupService._create_manifest(
                user_id, 
                sessions_report.rows_written,
                cars_report['count'],
                settings_report['count']
            )
            
            manifest_file = temp_dir / "manifest.json"
            with open(manifest_file, 'w') as f:
                json.dump(manifest, f, indent=2)
            
            # Create schema version file
            schema_file = temp_dir / "schema_version.txt"
            with open(schema_file, 'w') as f:
                f.write(BackupService.SCHEMA_VERSION)
            
            # Create ZIP file
            with zipfile.ZipFile(dst_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in temp_dir.glob('*'):
                    zipf.write(file_path, file_path.name)
            
            # Get ZIP file size
            zip_size = os.path.getsize(dst_zip)
            
            # Clean up temp directory
            import shutil
            shutil.rmtree(temp_dir)
            
            return BackupReport(
                success=True,
                path=dst_zip,
                file_count=5,  # manifest.json, schema_version.txt, sessions.csv, cars.csv, settings.json
                total_size_bytes=zip_size,
                manifest=manifest
            )
            
        except Exception as e:
            return BackupReport(
                success=False,
                errors=[f"Backup creation failed: {str(e)}"]
            )
    
    @staticmethod
    def restore_backup(
        user_id: int, 
        src_zip: str,
        mode: str = "merge",
        dry_run: bool = False,
        db_session=None
    ) -> ImportReport:
        """Restore from backup ZIP file"""
        if not os.path.exists(src_zip):
            raise FileNotFoundError(f"Backup file not found: {src_zip}")
        
        if mode not in ["merge", "replace"]:
            raise ValueError(f"Invalid mode: {mode}. Must be 'merge' or 'replace'")
        
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        report = ImportReport()
        
        try:
            # Extract ZIP to temporary directory
            temp_dir = Path(src_zip).parent / f"restore_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            temp_dir.mkdir(exist_ok=True)
            
            with zipfile.ZipFile(src_zip, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            # Validate backup structure
            required_files = ['manifest.json', 'schema_version.txt', 'sessions.csv', 'cars.csv', 'settings.json']
            for file_name in required_files:
                if not (temp_dir / file_name).exists():
                    raise ValidationError(f"Missing required backup file: {file_name}")
            
            # Read manifest
            with open(temp_dir / "manifest.json", 'r') as f:
                manifest = json.load(f)
            
            # Validate schema version compatibility
            schema_version = (temp_dir / "schema_version.txt").read_text().strip()
            if not BackupService._is_schema_compatible(schema_version):
                raise ValidationError(f"Incompatible schema version: {schema_version}. Expected {BackupService.SCHEMA_VERSION} or compatible")
            
            if mode == "replace":
                # Create auto-backup of current data
                auto_backup_path = f"{src_zip}.auto_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                auto_backup = BackupService.create_backup(user_id, auto_backup_path, db_session=session)
                if not auto_backup.success:
                    raise Exception(f"Failed to create auto-backup: {auto_backup.errors}")
                
                if not dry_run:
                    # Clear existing data
                    BackupService._clear_user_data(user_id, session)
            
            # Restore data
            if not dry_run:
                # Restore cars
                cars_restored = BackupService._restore_cars(user_id, temp_dir / "cars.csv", mode, session)
                report.inserted += cars_restored
                
                # Restore settings
                settings_restored = BackupService._restore_settings(user_id, temp_dir / "settings.json", mode, session)
                report.inserted += settings_restored
                
                # Restore sessions
                sessions_report = SessionIOService.import_sessions(
                    user_id, str(temp_dir / "sessions.csv"), dry_run=False, db_session=session
                )
                report.inserted += sessions_report.inserted
                report.skipped_duplicates += sessions_report.skipped_duplicates
                report.errors.extend(sessions_report.errors)
                report.warnings.extend(sessions_report.warnings)
                
                # Commit all changes
                session.commit()
            
            # Clean up temp directory
            import shutil
            shutil.rmtree(temp_dir)
            
            return report
            
        except Exception as e:
            # Clean up temp directory if it exists
            if 'temp_dir' in locals() and temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir)
            
            raise Exception(f"Restore failed: {str(e)}")
    
    @staticmethod
    def _export_cars(user_id: int, dst_path: str, db_session=None) -> Dict[str, Any]:
        """Export cars to CSV"""
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        cars = session.query(Car).filter_by(user_id=user_id).all()
        
        with open(dst_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'id', 'name', 'make', 'model', 'battery_kwh', 'efficiency_mpkwh',
                'recommended_full_charge_enabled', 'recommended_full_charge_frequency_value',
                'recommended_full_charge_frequency_unit', 'notes'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for car in cars:
                row = {
                    'id': car.id,
                    'name': car.display_name,
                    'make': car.make,
                    'model': car.model,
                    'battery_kwh': car.battery_kwh,
                    'efficiency_mpkwh': car.efficiency_mpkwh or '',
                    'recommended_full_charge_enabled': '1' if car.recommended_full_charge_enabled else '0',
                    'recommended_full_charge_frequency_value': car.recommended_full_charge_frequency_value or '',
                    'recommended_full_charge_frequency_unit': car.recommended_full_charge_frequency_unit or '',
                    'notes': ''
                }
                writer.writerow(row)
        
        return {'count': len(cars), 'path': dst_path}
    
    @staticmethod
    def _export_settings(user_id: int, dst_path: str, db_session=None) -> Dict[str, Any]:
        """Export settings to JSON"""
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        settings = session.query(Settings).filter_by(user_id=user_id).all()
        
        settings_dict = {}
        for setting in settings:
            # Keep encrypted values encrypted at rest
            if setting.encrypted:
                settings_dict[setting.key] = f"[ENCRYPTED_{len(setting.value or '')}chars]"
            else:
                settings_dict[setting.key] = setting.value
        
        with open(dst_path, 'w') as f:
            json.dump(settings_dict, f, indent=2)
        
        return {'count': len(settings), 'path': dst_path}
    
    @staticmethod
    def _create_manifest(
        user_id: int, 
        sessions_count: int, 
        cars_count: int, 
        settings_count: int
    ) -> Dict[str, Any]:
        """Create backup manifest"""
        return {
            "app": BackupService.APP_NAME,
            "version": BackupService.SCHEMA_VERSION,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
            "counts": {
                "cars": cars_count,
                "sessions": sessions_count,
                "settings": settings_count
            }
        }
    
    @staticmethod
    def _is_schema_compatible(schema_version: str) -> bool:
        """Check if schema version is compatible"""
        # For now, only exact version match
        # In the future, this could implement version compatibility logic
        return schema_version == BackupService.SCHEMA_VERSION
    
    @staticmethod
    def _clear_user_data(user_id: int, db_session=None):
        """Clear all data for a user (for replace mode)"""
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        # Delete in correct order to respect foreign keys
        session.query(ChargingSession).filter_by(user_id=user_id).delete()
        session.query(Car).filter_by(user_id=user_id).delete()
        session.query(Settings).filter_by(user_id=user_id).delete()
        
        session.commit()
    
    @staticmethod
    def _restore_cars(user_id: int, cars_csv_path: Path, mode: str, db_session=None) -> int:
        """Restore cars from CSV"""
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        restored_count = 0
        
        with open(cars_csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                # Check if car already exists (natural key: make+model)
                existing_car = session.query(Car).filter_by(
                    user_id=user_id,
                    make=row['make'],
                    model=row['model']
                ).first()
                
                if existing_car and mode == "merge":
                    # Update existing car
                    existing_car.battery_kwh = float(row['battery_kwh'])
                    existing_car.efficiency_mpkwh = float(row['efficiency_mpkwh']) if row['efficiency_mpkwh'] else None
                    existing_car.recommended_full_charge_enabled = row['recommended_full_charge_enabled'] == '1'
                    existing_car.recommended_full_charge_frequency_value = int(row['recommended_full_charge_frequency_value']) if row['recommended_full_charge_frequency_value'] else None
                    existing_car.recommended_full_charge_frequency_unit = row['recommended_full_charge_frequency_unit'] if row['recommended_full_charge_frequency_unit'] else None
                else:
                    # Create new car
                    car = Car(
                        user_id=user_id,
                        make=row['make'],
                        model=row['model'],
                        battery_kwh=float(row['battery_kwh']),
                        efficiency_mpkwh=float(row['efficiency_mpkwh']) if row['efficiency_mpkwh'] else None,
                        recommended_full_charge_enabled=row['recommended_full_charge_enabled'] == '1',
                        recommended_full_charge_frequency_value=int(row['recommended_full_charge_frequency_value']) if row['recommended_full_charge_frequency_value'] else None,
                        recommended_full_charge_frequency_unit=row['recommended_full_charge_frequency_unit'] if row['recommended_full_charge_frequency_unit'] else None
                    )
                    session.add(car)
                
                restored_count += 1
        
        return restored_count
    
    @staticmethod
    def _restore_settings(user_id: int, settings_json_path: Path, mode: str, db_session=None) -> int:
        """Restore settings from JSON"""
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        restored_count = 0
        
        with open(settings_json_path, 'r') as f:
            settings_dict = json.load(f)
        
        for key, value in settings_dict.items():
            # Skip encrypted placeholders
            if isinstance(value, str) and value.startswith('[ENCRYPTED_'):
                continue
            
            if mode == "merge":
                # Upsert setting
                Settings.set_setting(user_id, key, str(value))
            else:
                # Replace mode - create new setting
                setting = Settings(user_id=user_id, key=key, value=str(value))
                session.add(setting)
            
            restored_count += 1
        
        return restored_count
