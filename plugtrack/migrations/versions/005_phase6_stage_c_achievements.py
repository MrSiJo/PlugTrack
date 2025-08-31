#!/usr/bin/env python3
"""
Migration 005: Phase 6 Stage C - Achievements & Gamification
Created: 2024-12-21 Adds achievements table for gamification system
"""

import sys
import os

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from models.user import db
from sqlalchemy import text


def upgrade():
    """Apply Phase 6 Stage C - Add achievements table."""
    print("Applying migration 005: Phase 6 Stage C - Achievements & Gamification")
    
    # Create achievements table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS achievement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            car_id INTEGER,
            code VARCHAR(50) NOT NULL,
            name VARCHAR(100) NOT NULL,
            unlocked_date DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            value_json TEXT,
            FOREIGN KEY (user_id) REFERENCES user(id),
            FOREIGN KEY (car_id) REFERENCES car(id)
        )
    """))
    
    # Create indexes for efficient lookups
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_achievement_user_car_code 
        ON achievement(user_id, car_id, code)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_achievement_user_code 
        ON achievement(user_id, code)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_achievement_user_unlocked 
        ON achievement(user_id, unlocked_date)
    """))
    
    db.session.commit()
    
    print("✅ Phase 6 Stage C features added:")
    print("   • achievement table with proper indexes")
    print("   • Achievement model (models/achievement.py)")
    print("   • Achievement engine service (services/achievement_engine.py)")
    print("   • /api/achievements endpoint")
    print("   • Achievement hooks in session create/edit")
    print("   • Initial badges: 1000kwh, cheapest_mile, fastest_session, marathon_charge,")
    print("     free_charge_finder, night_owl, efficiency_master, road_warrior")


def downgrade():
    """Rollback Phase 6 Stage C."""
    print("Rolling back migration 005: Phase 6 Stage C - Achievements & Gamification")
    
    # Drop the achievements table
    db.session.execute(text("DROP TABLE IF EXISTS achievement"))
    db.session.commit()
    
    print("✅ Phase 6 Stage C rollback completed")
    print("   Note: Achievement services and hooks would need to be manually removed from code")


# Migration metadata
MIGRATION_ID = "005"
DESCRIPTION = "Phase 6 Stage C - Achievements & Gamification table and system"
DEPENDENCIES = ["004"]


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()

