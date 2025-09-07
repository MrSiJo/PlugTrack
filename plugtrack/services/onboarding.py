"""
Onboarding service for first-run user setup.
Handles initial user creation and optional car setup.
"""

from models.user import User, db
from models.car import Car
from flask import current_app


class OnboardingService:
    """Service for handling first-run onboarding flow."""
    
    @staticmethod
    def is_first_run():
        """
        Check if this is a first run (no users exist in database).
        
        Returns:
            bool: True if no users exist, False otherwise
        """
        try:
            user_count = User.query.count()
            return user_count == 0
        except Exception as e:
            # If there's an error (like missing tables), assume first run
            current_app.logger.warning(f"Error checking first run status: {e}. Assuming first run.")
            return True
    
    @staticmethod
    def create_initial_user(username, password):
        """
        Create the first user account.
        
        Args:
            username (str): Username for the new user
            password (str): Password for the new user
            
        Returns:
            dict: Result with success status and user data or error message
        """
        try:
            # Check if any users already exist
            if not OnboardingService.is_first_run():
                return {
                    'success': False,
                    'error': 'Users already exist. Onboarding is only available for first run.'
                }
            
            # Validate username
            if not username or len(username.strip()) < 3:
                return {
                    'success': False,
                    'error': 'Username must be at least 3 characters long.'
                }
            
            # Validate password
            if not password or len(password) < 6:
                return {
                    'success': False,
                    'error': 'Password must be at least 6 characters long.'
                }
            
            # Check if username already exists (shouldn't happen in first run, but safety check)
            existing_user = User.query.filter_by(username=username.strip()).first()
            if existing_user:
                return {
                    'success': False,
                    'error': 'Username already exists.'
                }
            
            # Create new user
            user = User(username=username.strip())
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            current_app.logger.info(f"Initial user created: {username}")
            
            return {
                'success': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'created_at': user.created_at
                }
            }
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating initial user: {e}")
            return {
                'success': False,
                'error': f'Failed to create user: {str(e)}'
            }
    
    @staticmethod
    def optionally_create_first_car(user_id, battery_kwh=None, efficiency_mpkwh=None, make=None, model=None):
        """
        Optionally create the first car for a user.
        
        Args:
            user_id (int): ID of the user to create car for
            battery_kwh (float, optional): Battery capacity in kWh
            efficiency_mpkwh (float, optional): Efficiency in miles per kWh
            make (str, optional): Car make
            model (str, optional): Car model
            
        Returns:
            dict: Result with success status and car data or error message
        """
        try:
            # Validate user exists
            user = User.query.get(user_id)
            if not user:
                return {
                    'success': False,
                    'error': 'User not found.'
                }
            
            # If no car data provided, return success without creating car
            if not battery_kwh and not efficiency_mpkwh and not make and not model:
                return {
                    'success': True,
                    'car': None,
                    'message': 'No car data provided, skipping car creation.'
                }
            
            # Validate required fields for car creation
            if not battery_kwh or battery_kwh <= 0:
                return {
                    'success': False,
                    'error': 'Battery capacity (kWh) is required and must be greater than 0.'
                }
            
            if not make or not make.strip():
                return {
                    'success': False,
                    'error': 'Car make is required.'
                }
            
            if not model or not model.strip():
                return {
                    'success': False,
                    'error': 'Car model is required.'
                }
            
            # Create new car
            car = Car(
                user_id=user_id,
                make=make.strip(),
                model=model.strip(),
                battery_kwh=float(battery_kwh),
                efficiency_mpkwh=float(efficiency_mpkwh) if efficiency_mpkwh else None,
                active=True
            )
            
            db.session.add(car)
            db.session.commit()
            
            current_app.logger.info(f"First car created for user {user_id}: {make} {model}")
            
            return {
                'success': True,
                'car': {
                    'id': car.id,
                    'make': car.make,
                    'model': car.model,
                    'battery_kwh': car.battery_kwh,
                    'efficiency_mpkwh': car.efficiency_mpkwh,
                    'active': car.active
                }
            }
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating first car: {e}")
            return {
                'success': False,
                'error': f'Failed to create car: {str(e)}'
            }
    
    @staticmethod
    def get_onboarding_status():
        """
        Get the current onboarding status.
        
        Returns:
            dict: Status information including first_run flag and user count
        """
        try:
            user_count = User.query.count()
            is_first_run = user_count == 0
            
            return {
                'is_first_run': is_first_run,
                'user_count': user_count,
                'onboarding_complete': not is_first_run
            }
        except Exception as e:
            current_app.logger.error(f"Error getting onboarding status: {e}")
            return {
                'is_first_run': False,
                'user_count': 0,
                'onboarding_complete': True,
                'error': str(e)
            }
