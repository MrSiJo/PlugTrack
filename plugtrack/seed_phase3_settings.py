#!/usr/bin/env python3
"""
Seed script for PlugTrack Phase 3 settings.
Populates default values for petrol_threshold_p_per_kwh, default_efficiency_mpkwh, and home_aliases_csv.
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugtrack import create_app
from plugtrack.models import db, Settings

def seed_phase3_settings():
    """Seed default Phase 3 settings for all users."""
    print("Starting Phase 3 settings seeding...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            # Get all users (assuming there's a way to identify unique users)
            # For now, we'll create global settings
            print("Creating default Phase 3 settings...")
            
            # Default Phase 3 settings
            default_settings = {
                'petrol_threshold_p_per_kwh': '52.5',
                'default_efficiency_mpkwh': '3.7',
                'home_aliases_csv': 'home,house,garage'
            }
            
            for key, value in default_settings.items():
                # Check if setting already exists
                existing = Settings.query.filter_by(key=key).first()
                
                if existing:
                    print(f"✓ Setting '{key}' already exists with value: {existing.value}")
                else:
                    # Create new setting
                    new_setting = Settings(key=key, value=value)
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
