#!/usr/bin/env python3
"""
Seed script for PlugTrack Phase 3 settings.
Populates default values for petrol_threshold_p_per_kwh, default_efficiency_mpkwh, and home_aliases_csv.
"""

import os
import sys

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app
from models.user import db, User
from models import Settings

def seed_phase3_settings():
    """Seed default Phase 3 settings for all users."""
    print("Starting Phase 3 settings seeding...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            # Get all existing users
            users = User.query.all()
            
            if not users:
                print("No users found. Creating default user...")
                # Create a default user
                default_user = User(username='default')
                default_user.set_password('default123')
                db.session.add(default_user)
                db.session.commit()
                users = [default_user]
                print(f"✓ Created default user: {default_user.username}")
            
            # Default Phase 3 settings
            default_settings = {
                'petrol_threshold_p_per_kwh': '52.5',
                'default_efficiency_mpkwh': '3.7',
                'home_aliases_csv': 'home,house,garage'
            }
            
            for user in users:
                print(f"Processing user: {user.username}")
                
                for key, value in default_settings.items():
                    # Check if setting already exists
                    existing = Settings.query.filter_by(user_id=user.id, key=key).first()
                    
                    if existing:
                        print(f"  ✓ Setting '{key}' already exists with value: {existing.value}")
                    else:
                        # Create new setting using the class method
                        Settings.set_setting(user.id, key, value)
                        print(f"  ✓ Created setting '{key}' with value: {value}")
            
            print("✓ Phase 3 settings seeding completed successfully!")
            
    except Exception as e:
        print(f"Error during settings seeding: {e}")
        print("Settings seeding failed!")
        return False
    
    return True

if __name__ == "__main__":
    success = seed_phase3_settings()
    sys.exit(0 if success else 1)
