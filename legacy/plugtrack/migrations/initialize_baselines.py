#!/usr/bin/env python3
"""
Initialize baseline sessions for existing PlugTrack data.
This script should be run after the baseline migration to set baseline flags for existing sessions.
"""

import sys
import os

# Add the parent directory (plugtrack) to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from __init__ import create_app
from services.baseline_manager import BaselineManager
from models.user import User

def initialize_baselines():
    """Initialize baseline sessions for all users and cars."""
    print("Starting baseline initialization...")
    
    try:
        # Create the Flask application
        app = create_app()
        
        # Enter application context
        with app.app_context():
            print("Initializing baseline sessions...")
            
            # Get all users
            users = User.query.all()
            
            if not users:
                print("⚠ No users found in the system")
                return False
            
            for user in users:
                print(f"Processing user: {user.username or user.id}")
                
                # Initialize baselines for all cars owned by this user
                BaselineManager.initialize_all_baselines(user.id)
                
                print(f"✓ Completed baseline initialization for user {user.username or user.id}")
            
            print("✓ Baseline initialization completed successfully!")
            
    except Exception as e:
        print(f"Error during baseline initialization: {e}")
        print("Baseline initialization failed!")
        return False
    
    return True

if __name__ == "__main__":
    success = initialize_baselines()
    sys.exit(0 if success else 1)
