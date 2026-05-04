from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import date
import json

@dataclass
class ImportReport:
    """Report for import operations"""
    ok_rows: int = 0
    inserted: int = 0
    skipped_duplicates: int = 0
    errors: List[Dict[str, Any]] = None
    warnings: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
    
    def add_error(self, row: int, field: str, message: str):
        """Add an error for a specific row and field"""
        self.errors.append({
            'row': row,
            'field': field,
            'message': message
        })
    
    def add_warning(self, row: int, field: str, message: str):
        """Add a warning for a specific row and field"""
        self.warnings.append({
            'row': row,
            'field': field,
            'message': message
        })
    
    def to_cli_text(self) -> str:
        """Convert report to CLI-friendly text"""
        lines = []
        lines.append(f"Import Summary:")
        lines.append(f"  ✓ Valid rows: {self.ok_rows}")
        lines.append(f"  ✓ Inserted: {self.inserted}")
        lines.append(f"  ⚠ Skipped duplicates: {self.skipped_duplicates}")
        
        if self.errors:
            lines.append(f"  ❌ Errors: {len(self.errors)}")
            for error in self.errors:
                lines.append(f"    Row {error['row']}: {error['field']} - {error['message']}")
        
        if self.warnings:
            lines.append(f"  ⚠ Warnings: {len(self.warnings)}")
            for warning in self.warnings:
                lines.append(f"    Row {warning['row']}: {warning['field']} - {warning['message']}")
        
        return "\n".join(lines)
    
    def to_json(self) -> Dict[str, Any]:
        """Convert report to JSON-serializable dict"""
        return {
            'ok_rows': self.ok_rows,
            'inserted': self.inserted,
            'skipped_duplicates': self.skipped_duplicates,
            'errors': self.errors,
            'warnings': self.warnings,
            'success': len(self.errors) == 0
        }

@dataclass
class ExportReport:
    """Report for export operations"""
    rows_written: int = 0
    path: str = ""
    filters_applied: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.filters_applied is None:
            self.filters_applied = {}
    
    def to_cli_text(self) -> str:
        """Convert report to CLI-friendly text"""
        lines = []
        lines.append(f"Export Summary:")
        lines.append(f"  ✓ Rows written: {self.rows_written}")
        lines.append(f"  📁 File: {self.path}")
        
        if self.filters_applied:
            lines.append(f"  🔍 Filters applied:")
            for key, value in self.filters_applied.items():
                if value is not None:
                    lines.append(f"    {key}: {value}")
        
        return "\n".join(lines)
    
    def to_json(self) -> Dict[str, Any]:
        """Convert report to JSON-serializable dict"""
        return {
            'rows_written': self.rows_written,
            'path': self.path,
            'filters_applied': self.filters_applied
        }

@dataclass
class BackupReport:
    """Report for backup operations"""
    success: bool = False
    path: str = ""
    file_count: int = 0
    total_size_bytes: int = 0
    manifest: Dict[str, Any] = None
    errors: List[str] = None
    
    def __post_init__(self):
        if self.manifest is None:
            self.manifest = {}
        if self.errors is None:
            self.errors = []
    
    def to_cli_text(self) -> str:
        """Convert report to CLI-friendly text"""
        if self.success:
            lines = []
            lines.append(f"Backup Summary:")
            lines.append(f"  ✓ Success: {self.path}")
            lines.append(f"  📁 Files: {self.file_count}")
            lines.append(f"  📊 Size: {self.total_size_bytes / 1024:.1f} KB")
            if self.manifest:
                lines.append(f"  📋 Manifest: {self.manifest.get('app', 'Unknown')} v{self.manifest.get('version', 'Unknown')}")
            return "\n".join(lines)
        else:
            lines = []
            lines.append(f"Backup Failed:")
            for error in self.errors:
                lines.append(f"  ❌ {error}")
            return "\n".join(lines)
    
    def to_json(self) -> Dict[str, Any]:
        """Convert report to JSON-serializable dict"""
        return {
            'success': self.success,
            'path': self.path,
            'file_count': self.file_count,
            'total_size_bytes': self.total_size_bytes,
            'manifest': self.manifest,
            'errors': self.errors
        }

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

def validate_date_format(date_str: str) -> date:
    """Validate and parse date string in YYYY-MM-DD format"""
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise ValidationError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD")

def validate_float_range(value: str, min_val: float = 0.0, field_name: str = "value") -> float:
    """Validate float value is within range"""
    try:
        float_val = float(value)
        if float_val < min_val:
            raise ValidationError(f"{field_name} must be >= {min_val}, got {float_val}")
        return float_val
    except ValueError:
        raise ValidationError(f"Invalid {field_name}: {value}. Expected a number")

def validate_charge_type(charge_type: str) -> str:
    """Validate charge type is AC or DC"""
    if charge_type.upper() not in ['AC', 'DC']:
        raise ValidationError(f"Invalid charge_type: {charge_type}. Must be 'AC' or 'DC'")
    return charge_type.upper()

def validate_odometer(odometer: str) -> int:
    """Validate odometer is a positive integer"""
    try:
        odometer_val = int(odometer)
        if odometer_val < 0:
            raise ValidationError(f"Odometer must be >= 0, got {odometer_val}")
        return odometer_val
    except ValueError:
        raise ValidationError(f"Invalid odometer: {odometer}. Expected a whole number")

def validate_duration_mins(duration: str) -> int:
    """Validate duration is a positive integer"""
    try:
        duration_val = int(duration)
        if duration_val <= 0:
            raise ValidationError(f"Duration must be > 0, got {duration_val}")
        return duration_val
    except ValueError:
        raise ValidationError(f"Invalid duration: {duration}. Expected a whole number")
