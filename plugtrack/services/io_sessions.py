import csv
import os
from datetime import date
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from services.validators import (
    ImportReport, ExportReport, ValidationError,
    validate_date_format, validate_float_range, validate_charge_type,
    validate_odometer, validate_duration_mins
)
from services.baseline_manager import BaselineManager

class SessionIOService:
    """Service for importing and exporting charging sessions"""
    
    # Required CSV headers for sessions
    REQUIRED_HEADERS = [
        'date', 'odometer', 'charge_type', 'charge_power_kw', 'location_label',
        'charge_network', 'charge_delivered_kwh', 'duration_mins', 'cost_per_kwh',
        'total_cost_gbp', 'soc_from', 'soc_to', 'ambient_temp_c', 'notes'
    ]
    
    @staticmethod
    def export_sessions(
        user_id: int, 
        dst_path: str,
        car_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        db_session: Optional[Session] = None
    ) -> ExportReport:
        """Export charging sessions to CSV file"""
        try:
            # Use provided session or fall back to global db.session
            session = db_session or db.session
            
            # Build query
            query = session.query(ChargingSession).filter_by(user_id=user_id)
            
            if car_id:
                query = query.filter_by(car_id=car_id)
            
            if date_from:
                query = query.filter(ChargingSession.date >= date_from)
            
            if date_to:
                query = query.filter(ChargingSession.date <= date_to)
            
            # Order by date and odometer for consistent export
            sessions = query.order_by(ChargingSession.date, ChargingSession.odometer).all()
            
            # Create directory if it doesn't exist
            dst_dir = os.path.dirname(dst_path)
            if dst_dir:  # Only create directory if there is a directory path
                os.makedirs(dst_dir, exist_ok=True)
            
            # Write CSV
            with open(dst_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=SessionIOService.REQUIRED_HEADERS)
                writer.writeheader()
                
                for session_obj in sessions:
                    # Map model fields to CSV fields
                    row = {
                        'date': session_obj.date.isoformat(),
                        'odometer': session_obj.odometer,
                        'charge_type': session_obj.charge_type,
                        'charge_power_kw': session_obj.charge_speed_kw,  # Map existing field
                        'location_label': session_obj.location_label,
                        'charge_network': session_obj.charge_network or '',
                        'charge_delivered_kwh': session_obj.charge_delivered_kwh,
                        'duration_mins': session_obj.duration_mins,
                        'cost_per_kwh': session_obj.cost_per_kwh,
                        'total_cost_gbp': session_obj.total_cost,  # Use computed property
                        'soc_from': session_obj.soc_from,
                        'soc_to': session_obj.soc_to,
                        'ambient_temp_c': '',  # Not in current model
                        'notes': session_obj.notes or ''
                    }
                    writer.writerow(row)
            
            # Build filters applied dict
            filters_applied = {}
            if car_id:
                filters_applied['car_id'] = car_id
            if date_from:
                filters_applied['date_from'] = date_from.isoformat()
            if date_to:
                filters_applied['date_to'] = date_to.isoformat()
            
            return ExportReport(
                rows_written=len(sessions),
                path=dst_path,
                filters_applied=filters_applied
            )
            
        except Exception as e:
            raise Exception(f"Export failed: {str(e)}")
    
    @staticmethod
    def import_sessions(
        user_id: int,
        src_path: str,
        car_id: Optional[int] = None,
        dry_run: bool = False,
        assume_currency: str = "GBP",
        db_session: Optional[Session] = None
    ) -> ImportReport:
        """Import charging sessions from CSV file"""
        if not os.path.exists(src_path):
            raise FileNotFoundError(f"Source file not found: {src_path}")
        
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        report = ImportReport()
        
        try:
            with open(src_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                
                # Validate headers
                if not all(header in reader.fieldnames for header in SessionIOService.REQUIRED_HEADERS):
                    missing = [h for h in SessionIOService.REQUIRED_HEADERS if h not in reader.fieldnames]
                    raise ValidationError(f"Missing required headers: {missing}")
                
                # Process rows
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (1-based + header)
                    try:
                        # Validate and parse row
                        validated_data = SessionIOService._validate_session_row(row, row_num)
                        
                        # Check for duplicates (idempotency key)
                        duplicate = SessionIOService._check_duplicate(
                            user_id, car_id or validated_data['car_id'], 
                            validated_data['date'], validated_data['odometer'], 
                            validated_data['charge_delivered_kwh'],
                            db_session=session
                        )
                        
                        if duplicate:
                            report.skipped_duplicates += 1
                            continue
                        
                        report.ok_rows += 1
                        
                        if not dry_run:
                            # Create session
                            session_obj = ChargingSession(
                                user_id=user_id,
                                car_id=car_id or validated_data['car_id'],
                                date=validated_data['date'],
                                odometer=validated_data['odometer'],
                                charge_type=validated_data['charge_type'],
                                charge_speed_kw=validated_data['charge_power_kw'],
                                location_label=validated_data['location_label'],
                                charge_network=validated_data['charge_network'],
                                charge_delivered_kwh=validated_data['charge_delivered_kwh'],
                                duration_mins=validated_data['duration_mins'],
                                cost_per_kwh=validated_data['cost_per_kwh'],
                                soc_from=validated_data['soc_from'],
                                soc_to=validated_data['soc_to'],
                                notes=validated_data['notes']
                            )
                            
                            session.add(session_obj)
                            report.inserted += 1
                    
                    except ValidationError as e:
                        report.add_error(row_num, 'validation', str(e))
                    except Exception as e:
                        report.add_error(row_num, 'general', f"Unexpected error: {str(e)}")
                
                if not dry_run and report.inserted > 0:
                    # Commit all sessions
                    session.commit()
                    
                    # Recalculate baselines for affected cars
                    affected_cars = set()
                    if car_id:
                        affected_cars.add(car_id)
                    else:
                        # Get all cars from imported sessions
                        for row_num, row in enumerate(reader, start=2):
                            if row_num in [e['row'] for e in report.errors]:
                                continue
                            try:
                                validated_data = SessionIOService._validate_session_row(row, row_num)
                                affected_cars.add(validated_data['car_id'])
                            except:
                                continue
                    
                    # Recalculate baselines
                    for car_id in affected_cars:
                        BaselineManager.recalculate_baseline_for_car(car_id)
            
            return report
            
        except Exception as e:
            raise Exception(f"Import failed: {str(e)}")
    
    @staticmethod
    def _validate_session_row(row: Dict[str, str], row_num: int) -> Dict[str, Any]:
        """Validate a single CSV row and return parsed data"""
        try:
            # Required fields
            date_val = validate_date_format(row['date'])
            odometer_val = validate_odometer(row['odometer'])
            charge_type_val = validate_charge_type(row['charge_type'])
            charge_delivered_kwh_val = validate_float_range(row['charge_delivered_kwh'], 0.0, 'charge_delivered_kwh')
            
            # Optional fields with defaults
            charge_power_kw = validate_float_range(row.get('charge_power_kw', '0'), 0.0, 'charge_power_kw') if row.get('charge_power_kw') else 0.0
            duration_mins = validate_duration_mins(row.get('duration_mins', '0')) if row.get('duration_mins') else 0
            cost_per_kwh = validate_float_range(row.get('cost_per_kwh', '0'), 0.0, 'cost_per_kwh') if row.get('cost_per_kwh') else 0.0
            soc_from = int(row.get('soc_from', '0')) if row.get('soc_from') else 0
            soc_to = int(row.get('soc_to', '0')) if row.get('soc_to') else 0
            
            # Auto-compute total_cost if not provided
            total_cost_gbp = 0.0
            if row.get('total_cost_gbp'):
                total_cost_gbp = validate_float_range(row['total_cost_gbp'], 0.0, 'total_cost_gbp')
            elif cost_per_kwh > 0 and charge_delivered_kwh_val > 0:
                total_cost_gbp = cost_per_kwh * charge_delivered_kwh_val
            
            # Determine car_id if not provided
            car_id = None
            if 'car_id' in row and row['car_id']:
                try:
                    car_id = int(row['car_id'])
                except ValueError:
                    raise ValidationError(f"Invalid car_id: {row['car_id']}")
            
            return {
                'date': date_val,
                'odometer': odometer_val,
                'charge_type': charge_type_val,
                'charge_power_kw': charge_power_kw,
                'location_label': row['location_label'],
                'charge_network': row.get('charge_network', ''),
                'charge_delivered_kwh': charge_delivered_kwh_val,
                'duration_mins': duration_mins,
                'cost_per_kwh': cost_per_kwh,
                'total_cost_gbp': total_cost_gbp,
                'soc_from': soc_from,
                'soc_to': soc_to,
                'ambient_temp_c': row.get('ambient_temp_c', ''),
                'notes': row.get('notes', ''),
                'car_id': car_id
            }
            
        except KeyError as e:
            raise ValidationError(f"Missing required field: {e}")
        except Exception as e:
            raise ValidationError(f"Row validation failed: {str(e)}")
    
    @staticmethod
    def _check_duplicate(
        user_id: int, 
        car_id: int, 
        date: date, 
        odometer: int, 
        charge_delivered_kwh: float,
        db_session: Optional[Session] = None
    ) -> bool:
        """Check if a session with the same idempotency key already exists"""
        # Use provided session or fall back to global db.session
        session = db_session or db.session
        
        existing = session.query(ChargingSession).filter_by(
            user_id=user_id,
            car_id=car_id,
            date=date,
            odometer=odometer,
            charge_delivered_kwh=charge_delivered_kwh
        ).first()
        
        return existing is not None
