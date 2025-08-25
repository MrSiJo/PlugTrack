#!/usr/bin/env python3
"""
Seed script for PlugTrack Phase 3 settings.
Populates default values for petrol_price_p_per_litre, petrol_mpg, default_efficiency_mpkwh, home_aliases_csv, and home_charging_speed_kw.
"""

import sys
import os

# Add the parent directory (plugtrack) to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from __init__ import create_app
from models.settings import Settings
from models.user import User
from models.charging_session import db

def seed_phase3_settings():
    """Seed default Phase 3 settings for all users."""
    print("Starting Phase 3 settings seeding...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            print("Creating default Phase 3 settings...")
            
            # Find the first user or create a global user_id
            first_user = User.query.first()
            if first_user:
                user_id = first_user.id
                print(f"✓ Using existing user ID: {user_id}")
            else:
                # If no users exist, use a special global user_id
                user_id = 0
                print(f"⚠ No users found, using global user_id: {user_id}")
            
            # Default Phase 3 settings
            default_settings = {
                'default_efficiency_mpkwh': '4.1',
                'home_aliases_csv': 'home,house,garage',
                'home_charging_speed_kw': '2.3',
                'petrol_price_p_per_litre': '128.9',
                'petrol_mpg': '60.0',
                'allow_efficiency_fallback': '1'
            }
            
            for key, value in default_settings.items():
                # Check if setting already exists
                existing = Settings.query.filter_by(user_id=user_id, key=key).first()
                
                if existing:
                    if existing.value != value:
                        # Update existing setting with new value
                        existing.value = value
                        print(f"✓ Updated setting '{key}' from '{existing.value}' to '{value}'")
                    else:
                        print(f"✓ Setting '{key}' already exists with correct value: {existing.value}")
                else:
                    # Create new setting
                    new_setting = Settings(user_id=user_id, key=key, value=value)
                    db.session.add(new_setting)
                    print(f"✓ Created setting '{key}' with value: {value}")
            
            # Commit all changes
            db.session.commit()
            
            print("✓ Phase 3 settings seeding completed successfully!")
            
    except Exception as e:
        print(f"Error during settings seeding: {e}")
        print("Settings seeding failed!")
        return False
    
    return True

if __name__ == "__main__":
    success = seed_phase3_settings()
    sys.exit(0 if success else 1)
