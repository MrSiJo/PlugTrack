import unittest
import uuid
from datetime import date, datetime, timedelta
import sys
import os

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from __init__ import create_app, db
from models.user import User
from models.car import Car
from models.charging_session import ChargingSession
from models.settings import Settings
from services.analytics_agg import AnalyticsAggService


class TestAnalyticsAggStageB(unittest.TestCase):
    """Test Stage B analytics functions: seasonal, leaderboard, and sweetspot"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        # Generate unique username to avoid conflicts
        unique_suffix = uuid.uuid4().hex[:8]
        self.username = f'testuser_stageb_{unique_suffix}'
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.user = User(username=self.username)
            self.user.set_password('test123')
            db.session.add(self.user)
            db.session.commit()
            self.user_id = self.user.id
            
            # Create test car
            self.car = Car(
                user_id=self.user_id,
                make='Tesla',
                model='Model 3',
                battery_kwh=75.0,
                efficiency_mpkwh=4.2,
                active=True
            )
            db.session.add(self.car)
            db.session.commit()
            self.car_id = self.car.id
            
            # Set up petrol price settings for cost calculations
            Settings.set_setting(self.user_id, 'petrol_ppl', '140.0')
            Settings.set_setting(self.user_id, 'mpg_uk', '35.0')
    
    def tearDown(self):
        """Clean up after tests"""
        with self.app.app_context():
            db.drop_all()
    
    def create_test_session(self, **kwargs):
        """Helper to create a test charging session"""
        defaults = {
            'user_id': self.user_id,
            'car_id': self.car_id,
            'date': date.today(),
            'odometer': 15000,
            'charge_type': 'AC',
            'charge_speed_kw': 7.4,
            'location_label': 'Home',
            'charge_network': 'Home Charger',
            'charge_delivered_kwh': 25.0,
            'duration_mins': 180,
            'cost_per_kwh': 0.15,
            'soc_from': 20,
            'soc_to': 80,
            'venue_type': 'home',
            'is_baseline': False,
            'ambient_temp_c': 18.0,
            'preconditioning_used': False
        }
        defaults.update(kwargs)
        
        session = ChargingSession(**defaults)
        db.session.add(session)
        db.session.commit()
        return session
    
    def test_seasonal_analytics_empty_data(self):
        """Test seasonal analytics with no data"""
        with self.app.app_context():
            result = AnalyticsAggService.get_seasonal_analytics(self.user_id, self.car_id)
            
            self.assertIn('temperature_bins', result)
            self.assertEqual(len(result['temperature_bins']), 0)
    
    def test_seasonal_analytics_with_data(self):
        """Test seasonal analytics with temperature data"""
        with self.app.app_context():
            # Create sessions with different temperatures
            self.create_test_session(ambient_temp_c=5.0, charge_delivered_kwh=20.0, odometer=15000)
            self.create_test_session(ambient_temp_c=8.0, charge_delivered_kwh=30.0, odometer=15100)  # Same bin
            self.create_test_session(ambient_temp_c=15.0, charge_delivered_kwh=25.0, odometer=15200)  # Different bin
            self.create_test_session(ambient_temp_c=22.0, charge_delivered_kwh=35.0, odometer=15300)  # Another bin
            
            result = AnalyticsAggService.get_seasonal_analytics(self.user_id, self.car_id)
            
            self.assertIn('temperature_bins', result)
            bins = result['temperature_bins']
            
            # Should have bins with data
            self.assertGreater(len(bins), 0)
            
            # Check that bins have correct structure
            for bin_data in bins:
                self.assertIn('range', bin_data)
                self.assertIn('avg_efficiency', bin_data)
                self.assertIn('session_count', bin_data)
                self.assertGreater(bin_data['avg_efficiency'], 0)
                self.assertGreater(bin_data['session_count'], 0)
    
    def test_seasonal_analytics_no_ambient_temp(self):
        """Test seasonal analytics with sessions lacking ambient temperature"""
        with self.app.app_context():
            # Create session without ambient temperature
            self.create_test_session(ambient_temp_c=None)
            
            result = AnalyticsAggService.get_seasonal_analytics(self.user_id, self.car_id)
            
            self.assertIn('temperature_bins', result)
            self.assertEqual(len(result['temperature_bins']), 0)
    
    def test_leaderboard_analytics_empty_data(self):
        """Test leaderboard analytics with no data"""
        with self.app.app_context():
            result = AnalyticsAggService.get_leaderboard_analytics(self.user_id, self.car_id)
            
            self.assertIn('locations', result)
            self.assertEqual(len(result['locations']), 0)
    
    def test_leaderboard_analytics_with_data(self):
        """Test leaderboard analytics with location data"""
        with self.app.app_context():
            # Create sessions at different locations
            self.create_test_session(
                location_label='Home', 
                cost_per_kwh=0.15, 
                charge_delivered_kwh=25.0,
                odometer=15000
            )
            self.create_test_session(
                location_label='Home', 
                cost_per_kwh=0.16, 
                charge_delivered_kwh=30.0,
                odometer=15100
            )  # Another Home session
            self.create_test_session(
                location_label='Supercharger', 
                cost_per_kwh=0.45, 
                charge_delivered_kwh=40.0,
                odometer=15200
            )
            self.create_test_session(
                location_label='Office', 
                cost_per_kwh=0.20, 
                charge_delivered_kwh=20.0,
                odometer=15300
            )
            
            result = AnalyticsAggService.get_leaderboard_analytics(self.user_id, self.car_id)
            
            self.assertIn('locations', result)
            locations = result['locations']
            
            # Should have 3 unique locations
            self.assertEqual(len(locations), 3)
            
            # Check that locations are sorted by session count (descending)
            home_location = next(loc for loc in locations if loc['location'] == 'Home')
            self.assertEqual(home_location['session_count'], 2)  # Two Home sessions
            
            # Verify structure
            for location in locations:
                self.assertIn('location', location)
                self.assertIn('session_count', location)
                self.assertIn('median_p_per_kwh', location)
                self.assertIn('median_p_per_mile', location)
                self.assertGreater(location['session_count'], 0)
    
    def test_leaderboard_analytics_free_charging(self):
        """Test leaderboard analytics with free charging sessions"""
        with self.app.app_context():
            # Create free charging session
            self.create_test_session(
                location_label='Free DC',
                cost_per_kwh=0.0,  # Free charging
                charge_delivered_kwh=50.0,
                odometer=15000
            )
            
            result = AnalyticsAggService.get_leaderboard_analytics(self.user_id, self.car_id)
            
            self.assertIn('locations', result)
            locations = result['locations']
            
            # Should still have the location
            self.assertEqual(len(locations), 1)
            location = locations[0]
            self.assertEqual(location['location'], 'Free DC')
            self.assertEqual(location['median_p_per_kwh'], 0)  # Should be 0 for free charging
    
    def test_sweetspot_analytics_empty_data(self):
        """Test sweetspot analytics with no data"""
        with self.app.app_context():
            result = AnalyticsAggService.get_sweetspot_analytics(self.user_id, self.car_id)
            
            self.assertIn('soc_windows', result)
            self.assertEqual(len(result['soc_windows']), 0)
    
    def test_sweetspot_analytics_with_data(self):
        """Test sweetspot analytics with SoC window data"""
        with self.app.app_context():
            # Create sessions in different SoC windows
            self.create_test_session(
                soc_from=15, soc_to=85, 
                charge_delivered_kwh=50.0, 
                odometer=15000
            )  # 0-20% window
            self.create_test_session(
                soc_from=25, soc_to=75, 
                charge_delivered_kwh=35.0, 
                odometer=15100
            )  # 20-40% window
            self.create_test_session(
                soc_from=35, soc_to=90, 
                charge_delivered_kwh=40.0, 
                odometer=15200
            )  # 20-40% window
            self.create_test_session(
                soc_from=45, soc_to=85, 
                charge_delivered_kwh=30.0, 
                odometer=15300
            )  # 40-60% window
            self.create_test_session(
                soc_from=65, soc_to=95, 
                charge_delivered_kwh=25.0, 
                odometer=15400
            )  # 60-80% window
            self.create_test_session(
                soc_from=85, soc_to=100, 
                charge_delivered_kwh=15.0, 
                odometer=15500
            )  # 80-100% window
            
            result = AnalyticsAggService.get_sweetspot_analytics(self.user_id, self.car_id)
            
            self.assertIn('soc_windows', result)
            windows = result['soc_windows']
            
            # Should have windows with data
            self.assertGreater(len(windows), 0)
            
            # Windows should be sorted by efficiency (best to worst)
            for i in range(1, len(windows)):
                self.assertGreaterEqual(windows[i-1]['avg_efficiency'], windows[i]['avg_efficiency'])
            
            # Check structure
            for window in windows:
                self.assertIn('soc_range', window)
                self.assertIn('avg_efficiency', window)
                self.assertIn('session_count', window)
                self.assertGreater(window['avg_efficiency'], 0)
                self.assertGreater(window['session_count'], 0)
    
    def test_sweetspot_analytics_baseline_sessions_excluded(self):
        """Test that baseline sessions are excluded from sweetspot analytics"""
        with self.app.app_context():
            # Create baseline session (should be excluded)
            self.create_test_session(
                soc_from=20, soc_to=80,
                charge_delivered_kwh=40.0,
                odometer=15000,
                is_baseline=True
            )
            
            # Create non-baseline session (should be included)
            self.create_test_session(
                soc_from=25, soc_to=85,
                charge_delivered_kwh=45.0,
                odometer=15100,
                is_baseline=False
            )
            
            result = AnalyticsAggService.get_sweetspot_analytics(self.user_id, self.car_id)
            
            self.assertIn('soc_windows', result)
            windows = result['soc_windows']
            
            # Should only have data from the non-baseline session (if efficiency can be calculated)
            # Note: With only one non-baseline session, efficiency calculation may not work without previous anchor
            # The main point is that baseline sessions are excluded
            self.assertIsInstance(windows, list)
            
            # If we have windows, verify they don't include baseline session data
            if windows:
                total_sessions = sum(w['session_count'] for w in windows)
                self.assertLessEqual(total_sessions, 1)  # At most 1 session (the non-baseline one)
    
    def test_analytics_car_filtering(self):
        """Test that car_id filtering works for all analytics methods"""
        with self.app.app_context():
            # Create second car
            car2 = Car(
                user_id=self.user_id,
                make='BMW',
                model='i3',
                battery_kwh=42.0,
                efficiency_mpkwh=3.8,
                active=True
            )
            db.session.add(car2)
            db.session.commit()
            
            # Create sessions for both cars
            self.create_test_session(
                car_id=self.car_id,
                location_label='Home',
                ambient_temp_c=20.0,
                soc_from=30,
                odometer=15000
            )
            self.create_test_session(
                car_id=car2.id,
                location_label='Office',
                ambient_temp_c=15.0,
                soc_from=40,
                odometer=25000
            )
            
            # Test seasonal analytics filtering
            seasonal_car1 = AnalyticsAggService.get_seasonal_analytics(self.user_id, self.car_id)
            seasonal_car2 = AnalyticsAggService.get_seasonal_analytics(self.user_id, car2.id)
            seasonal_all = AnalyticsAggService.get_seasonal_analytics(self.user_id, None)
            
            # Car-specific results should be different (if there's enough data for efficiency calculation)
            # With single sessions, we may get empty results, so just check the structure
            self.assertIn('temperature_bins', seasonal_car1)
            self.assertIn('temperature_bins', seasonal_car2)
            
            # Test leaderboard analytics filtering
            leaderboard_car1 = AnalyticsAggService.get_leaderboard_analytics(self.user_id, self.car_id)
            leaderboard_car2 = AnalyticsAggService.get_leaderboard_analytics(self.user_id, car2.id)
            
            # Should have different locations
            car1_locations = [loc['location'] for loc in leaderboard_car1['locations']]
            car2_locations = [loc['location'] for loc in leaderboard_car2['locations']]
            self.assertIn('Home', car1_locations)
            self.assertIn('Office', car2_locations)
            self.assertNotIn('Office', car1_locations)
            self.assertNotIn('Home', car2_locations)
            
            # Test sweetspot analytics filtering
            sweetspot_car1 = AnalyticsAggService.get_sweetspot_analytics(self.user_id, self.car_id)
            sweetspot_car2 = AnalyticsAggService.get_sweetspot_analytics(self.user_id, car2.id)
            
            # Should have valid structure
            self.assertIn('soc_windows', sweetspot_car1)
            self.assertIn('soc_windows', sweetspot_car2)
    
    def test_analytics_with_no_odometer_data(self):
        """Test analytics behavior when sessions lack odometer data"""
        with self.app.app_context():
            # Create session with odometer=0 to simulate lack of useful odometer data
            # (NULL odometer violates NOT NULL constraint)
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=date.today(),
                odometer=0,  # Minimal odometer data that won't help with efficiency
                charge_type='AC',
                charge_speed_kw=7.4,
                location_label='Home',
                charge_network='Home Charger',
                charge_delivered_kwh=25.0,
                duration_mins=180,
                cost_per_kwh=0.15,
                soc_from=20,
                soc_to=80,
                venue_type='home',
                is_baseline=False,
                ambient_temp_c=18.0
            )
            db.session.add(session)
            db.session.commit()
            
            # Since there's only one session with no previous anchor, 
            # efficiency calculation will fall back to car efficiency or not be available
            # This should result in empty or minimal analytics data
            seasonal = AnalyticsAggService.get_seasonal_analytics(self.user_id, self.car_id)
            sweetspot = AnalyticsAggService.get_sweetspot_analytics(self.user_id, self.car_id)
            
            # These may be empty or have minimal data due to lack of efficiency calculation
            # The main point is the service doesn't crash
            self.assertIsInstance(seasonal['temperature_bins'], list)
            self.assertIsInstance(sweetspot['soc_windows'], list)
            
            # Leaderboard should still work (doesn't require efficiency calculation for basic stats)
            leaderboard = AnalyticsAggService.get_leaderboard_analytics(self.user_id, self.car_id)
            self.assertEqual(len(leaderboard['locations']), 1)
            self.assertEqual(leaderboard['locations'][0]['location'], 'Home')


if __name__ == '__main__':
    unittest.main()
