#!/usr/bin/env python3
"""
Standalone script to initialize the PlugTrack database
"""

import os
import sys
from datetime import date

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app, db
from models import User, Car, ChargingSession, Settings
from migrations.migrate_phase3 import migrate_phase3
from migrations.add_phase2_indexes import add_phase2_indexes
from migrations.seed_phase3_settings import seed_phase3_settings
from migrations.initialize_baselines import initialize_baselines
from migrations.add_baseline_flag import run_baseline_migration
from migrations.run_efficiency_indexes import run_efficiency_indexes_migration

def init_db():
    """Initialize the database with sample data."""
    app = create_app()
    
    with app.app_context():
        db.create_all()

        # Run schema migrations and seeders for a fresh setup
        print("Running database migrations and seeders...")
        try:
            print("- Phase 3 migration (session_meta, venue_type)...")
            migrate_phase3()
        except Exception as e:
            print(f"⚠ Phase 3 migration error: {e}")

        try:
            print("- Add baseline flag and efficiency indexes...")
            run_baseline_migration()
        except Exception as e:
            print(f"⚠ Baseline flag migration error: {e}")

        try:
            print("- Add Phase 2 indexes...")
            add_phase2_indexes()
        except Exception as e:
            print(f"⚠ Phase 2 indexes error: {e}")

        try:
            print("- Add efficiency calculation indexes...")
            run_efficiency_indexes_migration()
        except Exception as e:
            print(f"⚠ Efficiency indexes migration error: {e}")

        try:
            print("- Seed Phase 3 settings...")
            seed_phase3_settings()
        except Exception as e:
            print(f"⚠ Settings seeding error: {e}")
        
        # Check if we already have a user
        if User.query.first() is None:
            # Create demo user
            user = User(username='demo')
            user.set_password('demo123')
            db.session.add(user)
            db.session.commit()
            
            # Create demo car
            car = Car(
                user_id=user.id,
                make='Tesla',
                model='Model 3',
                battery_kwh=75.0,
                efficiency_mpkwh=4.2,
                active=True,
                recommended_full_charge_enabled=True,
                recommended_full_charge_frequency_value=7,
                recommended_full_charge_frequency_unit='days'
            )
            db.session.add(car)
            db.session.commit()
            
            # Create demo charging session
            session = ChargingSession(
                user_id=user.id,
                car_id=car.id,
                date=date.today(),
                odometer=15000,
                charge_type='AC',
                charge_speed_kw=7.4,
                location_label='Home',
                charge_network='Home Charger',
                charge_delivered_kwh=25.5,
                duration_mins=180,
                cost_per_kwh=0.12,
                soc_from=20,
                soc_to=54,
                notes='Evening charge at home'
            )
            db.session.add(session)
            db.session.commit()
            
            print('Database initialized with demo data!')
            print('Username: demo, Password: demo123')
        else:
            print('Database already contains data.')

        # Initialize baseline sessions after data exists
        try:
            print("- Initialize baseline sessions...")
            initialize_baselines()
        except Exception as e:
            print(f"⚠ Baseline initialization error: {e}")

if __name__ == '__main__':
    init_db()
