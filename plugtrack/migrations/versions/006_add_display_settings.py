#!/usr/bin/env python3
"""
Migration 006: Add display settings for savings cards
Created: 2024-12-21 Adds show_savings_cards setting with default true
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


def upgrade():
    """Add default display settings for all users."""
    print("Applying migration 006: Add display settings")
    
    # Get all users
    users = User.query.all()
    
    for user in users:
        print(f"  Setting up display settings for user: {user.username}")
        
        # Add show_savings_cards setting if it doesn't exist
        existing = Settings.query.filter_by(user_id=user.id, key='show_savings_cards').first()
        if not existing:
            setting = Settings(user_id=user.id, key='show_savings_cards', value='1')
            db.session.add(setting)
            print(f"    ✓ Added show_savings_cards: 1 (enabled)")
        else:
            print(f"    - Exists show_savings_cards: {existing.value}")
    
    db.session.commit()
    print("✅ Display settings added successfully")


def downgrade():
    """Remove display settings."""
    print("Rolling back migration 006: Remove display settings")
    
    # Remove show_savings_cards settings
    Settings.query.filter_by(key='show_savings_cards').delete()
    db.session.commit()
    
    print("✅ Display settings removed successfully")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
