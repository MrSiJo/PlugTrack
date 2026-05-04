"""
Reminders API Service for PlugTrack Phase 6 Stage D
Wraps the existing reminder service to provide API-friendly data format.
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta, date
from models.car import Car
from services.reminders import ReminderService


class RemindersApiService:
    """Service to wrap existing reminder logic for API consumption"""
    
    @staticmethod
    def get_reminders_api(user_id: int, car_id: Optional[int] = None, 
                         date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict:
        """
        Get reminders in API format for /api/reminders endpoint.
        
        Args:
            user_id: User ID to check reminders for
            car_id: Optional car ID filter
            date_from: Optional date filter (for upcoming reminders)
            date_to: Optional date filter (for upcoming reminders)
            
        Returns:
            Dict with format: {"due": [...], "upcoming": [...]}
            Each item has: {car_id, car_name, last_full_date, due_by_date, overdue_days}
        """
        # Get reminder data from existing service
        reminder_data = ReminderService.check_full_charge_due(user_id, car_id)
        
        due_reminders = []
        upcoming_reminders = []
        
        # Process each reminder from the existing service
        for reminder in reminder_data.get('reminders', []):
            car_reminder = RemindersApiService._transform_reminder_data(reminder)
            
            if car_reminder['overdue_days'] > 0:
                # This is overdue (due)
                due_reminders.append(car_reminder)
            
        # Get upcoming reminders by checking cars that don't have reminders due yet
        upcoming_reminders = RemindersApiService._get_upcoming_reminders(
            user_id, car_id, date_from, date_to, due_reminders
        )
        
        return {
            "due": due_reminders,
            "upcoming": upcoming_reminders
        }
    
    @staticmethod
    def _transform_reminder_data(reminder: Dict) -> Dict:
        """
        Transform reminder data from existing service to API format.
        
        Args:
            reminder: Reminder dict from ReminderService
            
        Returns:
            Dict with API format fields
        """
        return {
            "car_id": reminder['car_id'],
            "car_name": reminder['car_make_model'],
            "last_full_date": reminder['last_high_charge_date'],
            "due_by_date": reminder['due_date'], 
            "overdue_days": reminder['days_overdue']
        }
    
    @staticmethod
    def _get_upcoming_reminders(user_id: int, car_id: Optional[int] = None,
                              date_from: Optional[date] = None, date_to: Optional[date] = None,
                              existing_due: List[Dict] = None) -> List[Dict]:
        """
        Get upcoming reminders for cars that don't have overdue reminders.
        
        Args:
            user_id: User ID
            car_id: Optional car filter
            date_from: Optional date range start
            date_to: Optional date range end  
            existing_due: List of cars that already have due reminders
            
        Returns:
            List of upcoming reminder dicts
        """
        if existing_due is None:
            existing_due = []
        
        # Get car IDs that already have due reminders
        due_car_ids = {r['car_id'] for r in existing_due}
        
        upcoming = []
        
        # Get cars to check
        query = Car.query.filter_by(user_id=user_id, active=True)
        if car_id:
            query = query.filter_by(id=car_id)
        
        cars = query.all()
        
        for car in cars:
            # Skip cars that already have due reminders
            if car.id in due_car_ids:
                continue
                
            # Check if this car has reminder settings and get upcoming reminder
            upcoming_reminder = RemindersApiService._calculate_upcoming_reminder(car, date_from, date_to)
            if upcoming_reminder:
                upcoming.append(upcoming_reminder)
        
        return upcoming
    
    @staticmethod
    def _calculate_upcoming_reminder(car: Car, date_from: Optional[date] = None, 
                                   date_to: Optional[date] = None) -> Optional[Dict]:
        """
        Calculate upcoming reminder for a specific car.
        
        Args:
            car: Car object
            date_from: Optional date filter start
            date_to: Optional date filter end
            
        Returns:
            Dict with upcoming reminder data or None if not applicable
        """
        # Check if car has reminder settings configured
        if not car.recommended_full_charge_enabled:
            return None
        
        if not car.recommended_full_charge_frequency_value or not car.recommended_full_charge_frequency_unit:
            return None
        
        # Calculate the frequency in days
        frequency_days = car.recommended_full_charge_frequency_value
        if car.recommended_full_charge_frequency_unit == 'months':
            frequency_days = frequency_days * 30  # Approximate months as 30 days
        
        # Find the last 95%+ charge for this car
        from models.charging_session import ChargingSession
        from sqlalchemy import desc
        
        last_high_charge = ChargingSession.query.filter_by(
            user_id=car.user_id,
            car_id=car.id
        ).filter(
            ChargingSession.soc_to >= 95
        ).order_by(desc(ChargingSession.date)).first()
        
        # Calculate reminder dates
        today = datetime.now().date()
        
        if not last_high_charge:
            # No high charge found - this should be handled as due, not upcoming
            return None
        
        days_since_last = (today - last_high_charge.date).days
        due_date = last_high_charge.date + timedelta(days=frequency_days)
        days_until_due = (due_date - today).days
        
        # Only include if it's upcoming (not overdue and within filter range)
        if days_until_due <= 0:
            return None
        
        # Apply date filters if provided
        if date_from and due_date < date_from:
            return None
        if date_to and due_date > date_to:
            return None
        
        return {
            "car_id": car.id,
            "car_name": f"{car.make} {car.model}",
            "last_full_date": last_high_charge.date.isoformat(),
            "due_by_date": due_date.isoformat(),
            "due_in_days": days_until_due
        }

