#!/usr/bin/env python3
"""
Migration 001: Initial PlugTrack schema
Created: 2024-12-21 Complete schema definition
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
    """Apply the initial schema migration."""
    print("Applying migration 001: Initial PlugTrack schema")
    
    # Create users table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(80) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # Create cars table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS car (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            make VARCHAR(100) NOT NULL,
            model VARCHAR(100) NOT NULL,
            battery_kwh FLOAT NOT NULL,
            efficiency_mpkwh FLOAT,
            active BOOLEAN DEFAULT 1,
            recommended_full_charge_enabled BOOLEAN DEFAULT 0,
            recommended_full_charge_frequency_value INTEGER,
            recommended_full_charge_frequency_unit VARCHAR(10),
            FOREIGN KEY (user_id) REFERENCES user(id)
        )
    """))
    
    # Create charging_session table with all current fields
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS charging_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            car_id INTEGER NOT NULL,
            date DATE NOT NULL,
            odometer INTEGER NOT NULL,
            charge_type VARCHAR(10) NOT NULL,
            charge_speed_kw FLOAT NOT NULL,
            location_label VARCHAR(200) NOT NULL,
            charge_network VARCHAR(100),
            charge_delivered_kwh FLOAT NOT NULL,
            duration_mins INTEGER NOT NULL,
            cost_per_kwh FLOAT NOT NULL,
            soc_from INTEGER NOT NULL,
            soc_to INTEGER NOT NULL,
            notes TEXT,
            venue_type VARCHAR(20),
            is_baseline BOOLEAN DEFAULT 0 NOT NULL,
            ambient_temp_c FLOAT,
            preconditioning_used BOOLEAN,
            preconditioning_events INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id),
            FOREIGN KEY (car_id) REFERENCES car(id)
        )
    """))
    
    # Create session_meta table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS session_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES charging_session(id) ON DELETE CASCADE,
            UNIQUE(session_id, key)
        )
    """))
    
    # Create settings table
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            key VARCHAR(100) NOT NULL,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id),
            UNIQUE(user_id, key)
        )
    """))
    
    # Create essential indexes
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_car_user ON car(user_id)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_cs_user ON charging_session(user_id)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_cs_car ON charging_session(car_id)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_cs_date ON charging_session(date)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_cs_user_car ON charging_session(user_id, car_id)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo ON charging_session(user_id, car_id, odometer)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_session_meta_session ON session_meta(session_id)
    """))
    
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_settings_user ON settings(user_id)
    """))
    
    db.session.commit()
    print("✅ Initial schema created successfully")


def downgrade():
    """Rollback the initial schema migration."""
    print("Rolling back migration 001: Initial PlugTrack schema")
    
    # Drop tables in reverse dependency order
    tables = [
        'session_meta',
        'charging_session', 
        'settings',
        'car',
        'user'
    ]
    
    for table in tables:
        db.session.execute(text(f"DROP TABLE IF EXISTS {table}"))
    
    db.session.commit()
    print("✅ Initial schema rolled back successfully")


# Migration metadata
MIGRATION_ID = "001"
DESCRIPTION = "Initial PlugTrack schema with all current tables and indexes"
DEPENDENCIES = []


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
