#!/usr/bin/env python3
"""
Test script for PlugTrack Phase 3 features.
"""

import os
import sys

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app
from models.user import db, User
from models import ChargingSession, Car, Settings

def test_phase3_features():
    """Test Phase 3 features."""
    print("Testing Phase 3 features...")
    
    try:
        app = create_app()
        
        with app.app_context():
            # Check if we have users
            users = User.query.all()
            print(f"✓ Users found: {[u.username for u in users]}")
            
            if users:
                user = users[0]
                print(f"Testing with user: {user.username}")
                
                # Check if we have cars
                cars = Car.query.filter_by(user_id=user.id).all()
                print(f"✓ Cars found: {[c.display_name for c in cars]}")
                
                if cars:
                    car = cars[0]
                    print(f"Testing with car: {car.display_name}")
                    
                    # Check if we have charging sessions
                    sessions = ChargingSession.query.filter_by(user_id=user.id).all()
                    print(f"✓ Charging sessions found: {len(sessions)}")
                    
                    if sessions:
                        session = sessions[0]
                        print(f"Testing with session: {session.id} from {session.date}")
                        
                        # Test session properties
                        print(f"  ✓ soc_range: {session.soc_range}")
                        print(f"  ✓ total_cost: {session.total_cost}")
                        print(f"  ✓ is_home_charging: {session.is_home_charging}")
                        
                        # Check settings
                        settings = Settings.query.filter_by(user_id=user.id).all()
                        print(f"✓ Settings found: {[(s.key, s.value) for s in settings]}")
                        
                        print("\n✓ Phase 3 features test completed successfully!")
                    else:
                        print("✗ No charging sessions found")
                else:
                    print("✗ No cars found")
            else:
                print("✗ No users found")
                
    except Exception as e:
        print(f"Error during testing: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_phase3_features()
    sys.exit(0 if success else 1)
