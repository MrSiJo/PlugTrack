#!/usr/bin/env python3
"""
Test script for currency functionality
"""
import os
import sys

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def test_currency_utility():
    """Test the currency utility functions"""
    print("Testing currency utility functions...")
    
    try:
        from utils.currency import get_currency_symbol, format_currency, get_currency_info
        
        # Test get_currency_symbol
        print(f"GBP symbol: {get_currency_symbol(1, 'GBP')}")
        print(f"EUR symbol: {get_currency_symbol(1, 'EUR')}")
        print(f"USD symbol: {get_currency_symbol(1, 'USD')}")
        
        # Test format_currency
        print(f"GBP format: {format_currency(15.50, 1, 'GBP')}")
        print(f"EUR format: {format_currency(15.50, 1, 'EUR')}")
        print(f"USD format: {format_currency(15.50, 1, 'USD')}")
        
        # Test get_currency_info
        gbp_info = get_currency_info(1, 'GBP')
        print(f"GBP info: {gbp_info}")
        
        print("✅ Currency utility tests passed!")
        
    except Exception as e:
        print(f"❌ Currency utility tests failed: {e}")
        return False
    
    return True

def test_settings_model():
    """Test the Settings model"""
    print("\nTesting Settings model...")
    
    try:
        from models.user import db, Settings
        from config import Config
        
        # Create a test app context
        from flask import Flask
        app = Flask(__name__)
        app.config.from_object(Config)
        
        with app.app_context():
            db.init_app(app)
            
            # Test setting and getting a currency setting
            test_user_id = 999  # Use a test user ID
            
            # Set a test currency
            Settings.set_setting(test_user_id, 'currency', 'EUR')
            
            # Get the setting back
            retrieved_currency = Settings.get_setting(test_user_id, 'currency', 'GBP')
            print(f"Retrieved currency: {retrieved_currency}")
            
            if retrieved_currency == 'EUR':
                print("✅ Settings model tests passed!")
            else:
                print("❌ Settings model test failed - currency not retrieved correctly")
                return False
                
    except Exception as e:
        print(f"❌ Settings model tests failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("🧪 Testing PlugTrack Currency System")
    print("=" * 40)
    
    success = True
    success &= test_currency_utility()
    success &= test_settings_model()
    
    if success:
        print("\n🎉 All tests passed! Currency system is working correctly.")
    else:
        print("\n💥 Some tests failed. Please check the errors above.")
        sys.exit(1)
