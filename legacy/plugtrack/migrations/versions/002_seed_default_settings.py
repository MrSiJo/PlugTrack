#!/usr/bin/env python3
"""
Migration 002: Seed default settings for all users
Created: 2024-12-21 Consolidates Phase 3/4/5 settings
"""

import sys
import os

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from models.user import db
from models.settings import Settings
from models.user import User
from sqlalchemy import text


def upgrade():
    """Seed default settings for all users."""
    print("Applying migration 002: Seed default settings")
    
    # Default settings with sensible values
    default_settings = {
        'petrol_threshold_p_per_kwh': '52.5',
        'default_efficiency_mpkwh': '4.1',
        'home_aliases_csv': 'home,house,garage',
        'home_charging_speed_kw': '2.3',
        'petrol_price_p_per_litre': '128.9',
        'petrol_mpg': '60.0',
        'allow_efficiency_fallback': '1'
    }
    
    # Get all users
    users = User.query.all()
    
    for user in users:
        print(f"  Setting up defaults for user: {user.username}")
        
        for key, value in default_settings.items():
            # Only add if setting doesn't exist
            existing = Settings.query.filter_by(user_id=user.id, key=key).first()
            if not existing:
                setting = Settings(user_id=user.id, key=key, value=value)
                db.session.add(setting)
                print(f"    ✓ Added {key}: {value}")
            else:
                print(f"    - Exists {key}: {existing.value}")
    
    db.session.commit()
    print("✅ Default settings seeded successfully")


def downgrade():
    """Remove default settings."""
    print("Rolling back migration 002: Remove default settings")
    
    default_keys = [
        'petrol_threshold_p_per_kwh',
        'default_efficiency_mpkwh', 
        'home_aliases_csv',
        'home_charging_speed_kw',
        'petrol_price_p_per_litre',
        'petrol_mpg',
        'allow_efficiency_fallback'
    ]
    
    for key in default_keys:
        Settings.query.filter_by(key=key).delete()
    
    db.session.commit()
    print("✅ Default settings removed successfully")


# Migration metadata
MIGRATION_ID = "002"
DESCRIPTION = "Seed default settings for all users"
DEPENDENCIES = ["001"]


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
