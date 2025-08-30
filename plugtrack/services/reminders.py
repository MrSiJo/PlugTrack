#!/usr/bin/env python3
"""
Reminder Engine Service for PlugTrack Phase 5-5.

Implements daily job checks for 100% charge reminders based on 
recommended_full_charge_frequency settings.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import func, and_, desc

from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from models.user import User


class ReminderService:
    """Service for managing reminders and notifications"""
    
    @staticmethod
    def check_full_charge_due(user_id: int, car_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Check if a 100% charge is due for a user's car(s).
        
        Args:
            user_id: User ID to check
            car_id: Optional specific car ID, if None checks all user's cars
            
        Returns:
            Dict containing reminder status and details
        """
        reminders = []
        
        # Get cars to check
        query = Car.query.filter_by(user_id=user_id, active=True)
        if car_id:
            query = query.filter_by(id=car_id)
        
        cars = query.all()
        
        for car in cars:
            reminder = ReminderService._check_car_full_charge_due(car)
            if reminder:
                reminders.append(reminder)
        
        return {
            'user_id': user_id,
            'checked_at': datetime.utcnow().isoformat(),
            'total_cars_checked': len(cars),
            'reminders_due': len(reminders),
            'reminders': reminders
        }
    
    @staticmethod
    def _check_car_full_charge_due(car: Car) -> Optional[Dict[str, Any]]:
        """
        Check if a specific car needs a 100% charge reminder.
        
        Args:
            car: Car object to check
            
        Returns:
            Dict with reminder details if due, None if not due
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
        
        # Find the last 100% charge for this car
        last_100_charge = ChargingSession.query.filter_by(
            user_id=car.user_id,
            car_id=car.id
        ).filter(
            ChargingSession.soc_to >= 100
        ).order_by(desc(ChargingSession.date)).first()
        
        # Calculate reminder status
        today = datetime.now().date()
        
        if not last_100_charge:
            # No 100% charge found - this is definitely overdue
            days_since_last = None
            due_date = today  # Consider it due immediately
            days_overdue = 1
        else:
            days_since_last = (today - last_100_charge.date).days
            due_date = last_100_charge.date + timedelta(days=frequency_days)
            days_overdue = (today - due_date).days if today > due_date else 0
        
        # Only return reminder if it's due or overdue
        if days_overdue <= 0:
            return None
        
        # Calculate urgency level
        if days_overdue <= 3:
            urgency = 'due'
        elif days_overdue <= 7:
            urgency = 'overdue'
        else:
            urgency = 'critical'
        
        return {
            'car_id': car.id,
            'car_make_model': f"{car.make} {car.model}",
            'frequency_days': frequency_days,
            'last_100_charge_date': last_100_charge.date.isoformat() if last_100_charge else None,
            'last_100_charge_id': last_100_charge.id if last_100_charge else None,
            'days_since_last_100': days_since_last,
            'due_date': due_date.isoformat(),
            'days_overdue': days_overdue,
            'urgency': urgency,
            'message': ReminderService._generate_reminder_message(car, days_overdue, urgency)
        }
    
    @staticmethod
    def _generate_reminder_message(car: Car, days_overdue: int, urgency: str) -> str:
        """Generate a user-friendly reminder message."""
        car_name = f"{car.make} {car.model}"
        
        if urgency == 'due':
            return f"Your {car_name} is due for a 100% charge (recommended every {car.recommended_full_charge_frequency_value} {car.recommended_full_charge_frequency_unit})."
        elif urgency == 'overdue':
            return f"Your {car_name} is {days_overdue} days overdue for a 100% charge. Consider charging to 100% to maintain battery health."
        else:  # critical
            return f"Your {car_name} is {days_overdue} days overdue for a 100% charge! Please charge to 100% soon to prevent battery degradation."
    
    @staticmethod
    def check_all_users() -> Dict[str, Any]:
        """
        Check all users for reminder-due cars.
        
        Returns:
            Dict containing summary of all reminders across all users
        """
        all_reminders = []
        total_users_checked = 0
        users_with_reminders = 0
        
        # Get all active users
        users = User.query.all()
        
        for user in users:
            total_users_checked += 1
            user_reminders = ReminderService.check_full_charge_due(user.id)
            
            if user_reminders['reminders_due'] > 0:
                users_with_reminders += 1
                user_reminders['username'] = user.username
                all_reminders.append(user_reminders)
        
        return {
            'checked_at': datetime.utcnow().isoformat(),
            'total_users_checked': total_users_checked,
            'users_with_reminders': users_with_reminders,
            'total_reminders': sum(r['reminders_due'] for r in all_reminders),
            'user_reminders': all_reminders
        }
    
    @staticmethod
    def log_reminder_check(check_results: Dict[str, Any], log_level: str = 'info') -> None:
        """
        Log reminder check results.
        
        Args:
            check_results: Results from check_all_users() or check_full_charge_due()
            log_level: Logging level ('info', 'warning', etc.)
        """
        import logging
        
        # Set up logging if not already configured
        logger = logging.getLogger('plugtrack.reminders')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(getattr(logging, log_level.upper()))
        
        if 'user_reminders' in check_results:
            # Results from check_all_users()
            total_reminders = check_results['total_reminders']
            users_with_reminders = check_results['users_with_reminders']
            
            if total_reminders == 0:
                logger.info("No 100% charge reminders due")
            else:
                logger.warning(f"{total_reminders} 100% charge reminders due for {users_with_reminders} users")
                
                for user_reminder in check_results['user_reminders']:
                    username = user_reminder.get('username', f"User {user_reminder['user_id']}")
                    reminder_count = user_reminder['reminders_due']
                    logger.info(f"  {username}: {reminder_count} reminders")
                    
                    for reminder in user_reminder['reminders']:
                        car_name = reminder['car_make_model']
                        urgency = reminder['urgency']
                        days_overdue = reminder['days_overdue']
                        logger.info(f"    {car_name}: {urgency} ({days_overdue} days overdue)")
        else:
            # Results from check_full_charge_due() for single user
            reminder_count = check_results['reminders_due']
            user_id = check_results['user_id']
            
            if reminder_count == 0:
                logger.info(f"No 100% charge reminders due for user {user_id}")
            else:
                logger.warning(f"{reminder_count} 100% charge reminders due for user {user_id}")
                
                for reminder in check_results['reminders']:
                    car_name = reminder['car_make_model']
                    urgency = reminder['urgency']
                    days_overdue = reminder['days_overdue']
                    logger.info(f"  {car_name}: {urgency} ({days_overdue} days overdue)")
