#!/usr/bin/env python3
"""
Basic test script to verify PlugTrack application structure
"""

import sys
import os

def test_imports():
    """Test that all modules can be imported"""
    try:
        # Add current directory to path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, current_dir)
        
        # Test imports
        from models.user import User, db
        from models.car import Car
        from models.charging_session import ChargingSession
        from models.settings import Settings
        from services.encryption import EncryptionService
        
        print("✓ All modules imported successfully")
        return True
        
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False

def test_app_creation():
    """Test that the Flask app can be created"""
    try:
        # Import after fixing path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, current_dir)
        
        from __init__ import create_app
        app = create_app()
        
        if app:
            print("✓ Flask app created successfully")
            return True
        else:
            print("✗ Flask app creation failed")
            return False
            
    except Exception as e:
        print(f"✗ App creation error: {e}")
        return False

def test_encryption():
    """Test encryption service"""
    try:
        from services.encryption import EncryptionService
        
        # Test encryption/decryption
        service = EncryptionService()
        test_data = "test123"
        encrypted = service.encrypt(test_data)
        decrypted = service.decrypt(encrypted)
        
        if decrypted == test_data:
            print("✓ Encryption service working correctly")
            return True
        else:
            print("✗ Encryption/decryption mismatch")
            return False
            
    except Exception as e:
        print(f"✗ Encryption test error: {e}")
        return False

def main():
    """Run all tests"""
    print("Running PlugTrack basic tests...\n")
    
    tests = [
        test_imports,
        test_app_creation,
        test_encryption
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print(f"Tests completed: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed! PlugTrack is ready to run.")
        return 0
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
