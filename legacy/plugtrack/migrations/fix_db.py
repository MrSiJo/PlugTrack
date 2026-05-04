#!/usr/bin/env python3
"""
Script to fix the database by properly creating all tables
"""

import os
import sys
from datetime import date

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app, db
from models import User, Car, ChargingSession, Settings, SessionMeta

def fix_database():
    """Fix the database by recreating all tables properly."""
    app = create_app()
    
    with app.app_context():
        print("🔧 Fixing database...")
        
        # Drop all tables first
        print("Dropping all existing tables...")
        db.drop_all()
        
        # Create all tables fresh
        print("Creating all tables fresh...")
        db.create_all()
        
        # Create demo user
        print("Creating demo user...")
        user = User(username='demo')
        user.set_password('demo123')
        db.session.add(user)
        db.session.commit()
        
        # Create demo car
        print("Creating demo car...")
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
        print("Creating demo charging session...")
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
            venue_type='home',
            is_baseline=True,
            ambient_temp_c=18.5,
            preconditioning_used=False,
            preconditioning_events=0,
            notes='Evening charge at home'
        )
        db.session.add(session)
        db.session.commit()
        
        # Create some default settings
        print("Creating default settings...")
        settings_data = [
            ('default_efficiency_mpkwh', '4.1', False),
            ('home_aliases_csv', 'home,house,garage', False),
            ('home_charging_speed_kw', '2.3', False),
            ('petrol_price_p_per_litre', '128.9', False),
            ('petrol_mpg', '60.0', False),
            ('allow_efficiency_fallback', '1', False)
        ]
        
        for key, value, encrypted in settings_data:
            setting = Settings(
                user_id=user.id,
                key=key,
                value=value,
                encrypted=encrypted
            )
            db.session.add(setting)
        
        db.session.commit()
        
        print("✅ Database fixed successfully!")
        print("Username: demo, Password: demo123")
        
        # Verify the charging_session table structure
        print("\n🔍 Verifying table structure...")
        try:
            from sqlalchemy import text
            result = db.session.execute(text("PRAGMA table_info(charging_session);"))
            columns = result.fetchall()
            print(f"charging_session table has {len(columns)} columns:")
            for col in columns:
                col_id, col_name, col_type, not_null, default_val, pk = col
                print(f"  {col_name}: {col_type} {'NOT NULL' if not_null else 'NULL'} {'PK' if pk else ''}")
            
            # Check if we can query the table
            session_count = ChargingSession.query.count()
            print(f"\n✅ charging_session table has {session_count} rows")
            
        except Exception as e:
            print(f"❌ Error verifying table: {e}")

if __name__ == '__main__':
    fix_database()
