#!/usr/bin/env python3
"""
Script to check and fix car status issues
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app
from models.car import Car
from models.user import User, db

def check_car_status():
    """Check the status of all cars in the database"""
    app = create_app()
    
    with app.app_context():
        # Check if the active column exists
        try:
            # Try to query the active field
            cars = Car.query.all()
            print(f"Found {len(cars)} cars in database")
            
            for car in cars:
                print(f"Car ID {car.id}: {car.make} {car.model}")
                print(f"  User ID: {car.user_id}")
                print(f"  Active: {getattr(car, 'active', 'FIELD_NOT_FOUND')}")
                print(f"  Battery: {car.battery_kwh} kWh")
                print(f"  Efficiency: {car.efficiency_mpkwh} mi/kWh")
                print("  ---")
                
        except Exception as e:
            print(f"Error querying cars: {e}")
            print("This might indicate a database schema issue")
            
        # Check users
        try:
            users = User.query.all()
            print(f"\nFound {len(users)} users in database")
            for user in users:
                print(f"User ID {user.id}: {user.username}")
        except Exception as e:
            print(f"Error querying users: {e}")

if __name__ == '__main__':
    check_car_status()
