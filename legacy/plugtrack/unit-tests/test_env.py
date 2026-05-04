#!/usr/bin/env python3
"""
Test environment variable loading
"""

import os
from dotenv import load_dotenv

def test_env_loading():
    """Test if environment variables are being loaded correctly"""
    print("🔍 Testing environment variable loading...")
    
    # Check before loading
    print(f"1. DATABASE_URL before load_dotenv(): {os.environ.get('DATABASE_URL')}")
    
    # Try to load .env file
    print("2. Loading .env file...")
    result = load_dotenv()
    print(f"   load_dotenv() returned: {result}")
    
    # Check after loading
    print(f"3. DATABASE_URL after load_dotenv(): {os.environ.get('DATABASE_URL')}")
    
    # Check if .env file exists
    env_file = '.env'
    if os.path.exists(env_file):
        print(f"4. .env file exists: {os.path.abspath(env_file)}")
        print(f"   File size: {os.path.getsize(env_file)} bytes")
        
        # Read first few lines
        with open(env_file, 'r') as f:
            lines = f.readlines()[:5]
            print("   First 5 lines:")
            for i, line in enumerate(lines, 1):
                print(f"     {i}: {line.strip()}")
    else:
        print("4. .env file not found!")
    
    # Check current working directory
    print(f"5. Current working directory: {os.getcwd()}")
    
    # Try to find .env file in parent directories
    current_dir = os.getcwd()
    for i in range(3):  # Check up to 3 levels up
        parent_dir = os.path.dirname(current_dir)
        env_in_parent = os.path.join(parent_dir, '.env')
        if os.path.exists(env_in_parent):
            print(f"6. Found .env in parent directory: {env_in_parent}")
            break
        current_dir = parent_dir

if __name__ == '__main__':
    test_env_loading()
