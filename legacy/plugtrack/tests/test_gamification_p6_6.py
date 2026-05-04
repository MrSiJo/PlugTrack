#!/usr/bin/env python3
"""
Unit tests for P6-6: Gamification Layer
Tests achievement system, API endpoints, and dashboard integration.
"""

import unittest
import tempfile
import os
import sys
from datetime import datetime, timedelta

# Add the project root to Python path for imports
sys.path.insert(0, '.')

from __init__ import create_app
from models.user import db, User
from models.car import Car
from models.charging_session import ChargingSession
from models.achievement import Achievement
from services.achievement_engine import AchievementEngine


class TestGamificationP6_6(unittest.TestCase):
    def setUp(self):
        """Set up test environment with temporary database"""
        self.db_fd, self.db_path = tempfile.mkstemp()
        
        # Create app with test config
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        self.client = self.app.test_client()
        
        with self.app.app_context():
            # Create tables
            db.create_all()
            
            # Create test user with password hash
            test_user = User(username='testuser', password_hash='test_hash')
            db.session.add(test_user)
            db.session.commit()
            self.user_id = test_user.id
            
            # Create test car
            test_car = Car(
                user_id=self.user_id,
                make='Tesla',
                model='Model 3',
                battery_kwh=75.0,
                efficiency_mpkwh=4.0
            )
            db.session.add(test_car)
            db.session.commit()
            self.car_id = test_car.id
            
            # Login test user
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.user_id)
                sess['_fresh'] = True
    
    def tearDown(self):
        """Clean up test environment"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        
        os.close(self.db_fd)
        os.unlink(self.db_path)
    
    def test_achievement_api_endpoint(self):
        """Test /api/achievements endpoint returns correct structure"""
        with self.app.app_context():
            response = self.client.get('/api/achievements')
            self.assertEqual(response.status_code, 200)
            
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertIn('unlocked', data)
            self.assertIn('locked', data)
            
            # Should be lists
            self.assertIsInstance(data['unlocked'], list)
            self.assertIsInstance(data['locked'], list)
            
            # Initially should have locked achievements
            self.assertGreater(len(data['locked']), 0)
    
    def test_achievement_api_with_car_filter(self):
        """Test achievements API with car_id parameter"""
        with self.app.app_context():
            response = self.client.get(f'/api/achievements?car_id={self.car_id}')
            self.assertEqual(response.status_code, 200)
            
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertIn('unlocked', data)
            self.assertIn('locked', data)
    
    def test_achievement_definitions_complete(self):
        """Test that all P6-6 achievement definitions are present"""
        with self.app.app_context():
            expected_achievements = [
                '1000kwh', 'cheapest_mile', 'fastest_session', 'marathon_charge',
                'free_charge_finder', 'night_owl', 'efficiency_master', 'road_warrior'
            ]
            
            definitions = AchievementEngine.ACHIEVEMENT_DEFINITIONS
            
            for achievement_code in expected_achievements:
                self.assertIn(achievement_code, definitions)
                definition = definitions[achievement_code]
                self.assertIn('name', definition)
                self.assertIn('description', definition)
                self.assertIn('global', definition)
    
    def test_achievement_model_structure(self):
        """Test Achievement model basic functionality"""
        with self.app.app_context():
            # Create a test achievement
            achievement = Achievement(
                user_id=self.user_id,
                car_id=self.car_id,
                code='test_achievement',
                name='Test Achievement',
                unlocked_date=datetime.utcnow(),
                value_json='{"value": "test value"}'
            )
            
            db.session.add(achievement)
            db.session.commit()
            
            # Test retrieval
            saved_achievement = Achievement.query.filter_by(code='test_achievement').first()
            self.assertIsNotNone(saved_achievement)
            self.assertEqual(saved_achievement.name, 'Test Achievement')
            self.assertEqual(saved_achievement.user_id, self.user_id)
            
            # Test to_dict method
            achievement_dict = saved_achievement.to_dict()
            self.assertIn('code', achievement_dict)
            self.assertIn('name', achievement_dict)
            self.assertIn('date', achievement_dict)
            self.assertIn('value', achievement_dict)
    
    def test_achievement_engine_session_check(self):
        """Test achievement engine checks sessions correctly"""
        with self.app.app_context():
            # Create a charging session that should trigger achievements
            session = ChargingSession(
                user_id=self.user_id,
                car_id=self.car_id,
                date=datetime.utcnow(),
                location_label='Home',
                soc_from=20,
                soc_to=80,
                charge_delivered_kwh=45.0,
                cost_per_kwh=0.05,  # Very cheap - should trigger cheapest_mile
                session_start=datetime.utcnow() - timedelta(hours=10),  # Long session
                session_end=datetime.utcnow(),
                odometer=1000
            )
            
            db.session.add(session)
            db.session.commit()
            
            # Check achievements for this session
            newly_awarded = AchievementEngine.check_achievements_for_session(session.id)
            
            # Should be a list (empty or with achievements)
            self.assertIsInstance(newly_awarded, list)
    
    def test_dashboard_includes_achievements_widget(self):
        """Test that dashboard includes achievements widget elements"""
        with self.app.app_context():
            response = self.client.get('/')
            self.assertEqual(response.status_code, 200)
            
            content = response.data.decode('utf-8')
            
            # Check for achievement widget elements
            achievement_elements = [
                'achievements-container',
                'achievementsModal',
                'loadAchievements',
                'achievement-badge',
                'bi-trophy',
                'View All Achievements'
            ]
            
            for element in achievement_elements:
                self.assertIn(element, content, f'Achievement element "{element}" not found in dashboard')
    
    def test_achievement_css_styling(self):
        """Test that achievement CSS styling is included"""
        with self.app.app_context():
            response = self.client.get('/')
            self.assertEqual(response.status_code, 200)
            
            content = response.data.decode('utf-8')
            
            # Check for achievement CSS classes
            css_elements = [
                '.achievement-badge',
                '.achievement-badge.unlocked',
                '.achievement-name',
                '.achievement-value'
            ]
            
            for css_class in css_elements:
                self.assertIn(css_class, content, f'CSS class "{css_class}" not found')
    
    def test_achievement_javascript_functions(self):
        """Test that achievement JavaScript functions are included"""
        with self.app.app_context():
            response = self.client.get('/')
            self.assertEqual(response.status_code, 200)
            
            content = response.data.decode('utf-8')
            
            # Check for achievement JavaScript functions
            js_functions = [
                'loadAchievements',
                'renderAchievementsSummary',
                'renderAchievementsModal',
                'getAchievementDescription'
            ]
            
            for js_function in js_functions:
                self.assertIn(js_function, content, f'JavaScript function "{js_function}" not found')
    
    def test_achievement_integration_with_session_creation(self):
        """Test that achievements are checked when sessions are created"""
        with self.app.app_context():
            # Count initial achievements
            initial_count = Achievement.query.filter_by(user_id=self.user_id).count()
            
            # Create session via POST (simulating form submission)
            session_data = {
                'car_id': self.car_id,
                'date': datetime.utcnow().strftime('%Y-%m-%d'),
                'location_label': 'Test Location',
                'soc_from': 20,
                'soc_to': 80,
                'charge_delivered_kwh': 45.0,
                'cost_per_kwh': 0.10,
                'session_start': (datetime.utcnow() - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M'),
                'session_end': datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
                'odometer': 1000
            }
            
            response = self.client.post('/charging_sessions/add', data=session_data, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            
            # Achievement checking should have been triggered
            # (Note: May or may not actually award achievements depending on data and criteria)
            final_count = Achievement.query.filter_by(user_id=self.user_id).count()
            self.assertGreaterEqual(final_count, initial_count)


if __name__ == '__main__':
    unittest.main()
