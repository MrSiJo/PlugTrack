#!/usr/bin/env python3
"""
Seed script for PlugTrack Phase 4 settings.
Populates default values for all Phase 4 required settings.
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

def seed_phase4_settings():
    """Seed default Phase 4 settings for all users."""
    print("Starting Phase 4 settings seeding...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            print("Creating default Phase 4 settings...")
            
            # Find the first user or create a global user_id
            first_user = User.query.first()
            if first_user:
                user_id = first_user.id
                print(f"✓ Using existing user ID: {user_id}")
            else:
                # If no users exist, use a special global user_id
                user_id = 0
                print(f"⚠ No users found, using global user_id: {user_id}")
            
            # Default Phase 4 settings (as specified in requirements)
            default_settings = {
                'default_efficiency_mpkwh': '4.1',
                'home_aliases_csv': 'home,house,garage',
                'home_charging_speed_kw': '2.3',
                'petrol_price_p_per_litre': '128.9',
                'petrol_mpg': '60.0',
                'allow_efficiency_fallback': '1'
            }
            
            # Additional settings that may be useful
            additional_settings = {
                'currency': 'GBP',
                'timezone': 'Europe/London',
                'date_format': 'YYYY-MM-DD',
                'decimal_places': '2'
            }
            
            # Combine all settings
            all_settings = {**default_settings, **additional_settings}
            
            for key, value in all_settings.items():
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
            
            print("✓ Phase 4 settings seeding completed successfully!")
            print(f"✓ Seeded {len(all_settings)} settings for user {user_id}")
            
            # Print summary of key settings
            print("\nKey Phase 4 Settings:")
            for key in default_settings.keys():
                setting = Settings.query.filter_by(user_id=user_id, key=key).first()
                if setting:
                    print(f"  {key}: {setting.value}")
            
    except Exception as e:
        print(f"Error during settings seeding: {e}")
        print("Settings seeding failed!")
        return False
    
    return True

if __name__ == "__main__":
    success = seed_phase4_settings()
    sys.exit(0 if success else 1)
