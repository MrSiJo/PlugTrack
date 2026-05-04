"""
Achievement Engine for PlugTrack Phase 6 Stage C
Handles gamification badges and achievements for users.
"""

import json
from typing import Dict, List, Optional
from sqlalchemy import func, desc, asc
from models.user import db
from models.achievement import Achievement
from models.charging_session import ChargingSession
from models.car import Car
from services.derived_metrics import DerivedMetricsService
from datetime import datetime, timedelta


class AchievementEngine:
    """Engine for checking and awarding achievements based on charging session data"""
    
    # Achievement definitions from P6-6
    ACHIEVEMENT_DEFINITIONS = {
        '1000kwh': {
            'name': '1000 kWh Club',
            'description': 'Delivered 1000+ kWh of energy',
            'global': True  # Across all cars
        },
        'cheapest_mile': {
            'name': 'Cheapest Mile',
            'description': 'Found the cheapest cost per mile session',
            'global': False  # Per car
        },
        'fastest_session': {
            'name': 'Fastest Session',
            'description': 'Highest average power charging session',
            'global': False  # Per car
        },
        'marathon_charge': {
            'name': 'Marathon Charge',
            'description': 'Charging session longer than 8 hours',
            'global': False  # Per car
        },
        'free_charge_finder': {
            'name': 'Free Charge Finder',
            'description': 'Found a free charging session',
            'global': False  # Per car
        },
        'night_owl': {
            'name': 'Night Owl',
            'description': 'Charged between midnight and 6 AM',
            'global': False  # Per car
        },
        'efficiency_master': {
            'name': 'Efficiency Master',
            'description': 'Achieved 5+ mi/kWh efficiency in a session',
            'global': False  # Per car
        },
        'road_warrior': {
            'name': 'Road Warrior',
            'description': 'Completed 100+ charging sessions',
            'global': False  # Per car
        },
        
        # Additional P6-6 achievements
        'winter_warrior': {
            'name': 'Winter Warrior',
            'description': 'Charge completed <5°C ambient temp',
            'global': False
        },
        'first_plug': {
            'name': 'First Plug',
            'description': 'First tracked session',
            'global': False
        },
        'road_to_10000': {
            'name': 'Road to 10,000',
            'description': 'Cumulative 10,000 kWh charged',
            'global': True
        },
        'century_session': {
            'name': 'Century Session',
            'description': '100th charging session logged',
            'global': False
        },
        'penny_pincher': {
            'name': 'Penny Pincher',
            'description': 'Session cost < £1',
            'global': False
        },
        'savers_streak': {
            'name': "Saver's Streak",
            'description': '7 sessions in a row below average cost/kWh',
            'global': False
        },
        'off_peak_champ': {
            'name': 'Off-Peak Champ',
            'description': 'Most sessions completed off-peak',
            'global': False
        },
        'rapid_riser': {
            'name': 'Rapid Riser',
            'description': 'First DC >100kW session',
            'global': False
        },
        'sprint_finish': {
            'name': 'Sprint Finish',
            'description': '20–80% in under 25 minutes',
            'global': False
        },
        'solar_soaker': {
            'name': 'Solar Soaker',
            'description': 'Session cost = £0 / solar-powered',
            'global': False
        },
        'heatwave_hero': {
            'name': 'Heatwave Hero',
            'description': 'Charge in >30°C ambient temp',
            'global': False
        },
        'forgotten_plug': {
            'name': 'Forgotten Plug',
            'description': 'Session >12 hours but <5 kWh delivered',
            'global': False
        },
        'range_anxiety': {
            'name': 'Range Anxiety?',
            'description': 'Charge started <5% SoC',
            'global': False
        },
        'explorer': {
            'name': 'Explorer',
            'description': '10 different networks used',
            'global': False
        },
        'staycationer': {
            'name': 'Staycationer',
            'description': '90%+ of sessions at home',
            'global': False
        }
    }
    
    @staticmethod
    def check_achievements_for_session(session_id: int) -> List[str]:
        """
        Check and award achievements triggered by a specific session.
        Returns list of newly awarded achievement codes.
        """
        from models.charging_session import ChargingSession
        
        session = ChargingSession.query.get(session_id)
        if not session:
            return []
        
        newly_awarded = []
        
        # Check all achievement types
        for achievement_code in AchievementEngine.ACHIEVEMENT_DEFINITIONS.keys():
            if AchievementEngine._check_and_award_achievement(session, achievement_code):
                newly_awarded.append(achievement_code)
        
        return newly_awarded
    
    @staticmethod
    def check_all_achievements_for_user(user_id: int, car_id: Optional[int] = None) -> List[str]:
        """
        Bulk check all achievements for a user (optionally for specific car).
        Useful for initialization or backfill.
        Returns list of newly awarded achievement codes.
        """
        newly_awarded = []
        
        # Get all sessions for the user/car
        query = ChargingSession.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        sessions = query.all()
        
        for session in sessions:
            for achievement_code in AchievementEngine.ACHIEVEMENT_DEFINITIONS.keys():
                if AchievementEngine._check_and_award_achievement(session, achievement_code):
                    newly_awarded.append(achievement_code)
        
        return newly_awarded
    
    @staticmethod
    def _check_and_award_achievement(session: ChargingSession, achievement_code: str) -> bool:
        """
        Check if a session triggers an achievement and award it if not already awarded.
        Returns True if achievement was newly awarded, False if already had it or didn't qualify.
        """
        achievement_def = AchievementEngine.ACHIEVEMENT_DEFINITIONS.get(achievement_code)
        if not achievement_def:
            return False
        
        # Check if already awarded (idempotent)
        car_id_filter = session.car_id if not achievement_def['global'] else None
        existing = Achievement.query.filter_by(
            user_id=session.user_id,
            car_id=car_id_filter,
            code=achievement_code
        ).first()
        
        if existing:
            return False  # Already awarded
        
        # Check if achievement criteria is met
        criteria_met, value_context = AchievementEngine._check_achievement_criteria(
            session, achievement_code
        )
        
        if criteria_met:
            # Award the achievement
            achievement = Achievement(
                user_id=session.user_id,
                car_id=car_id_filter,
                code=achievement_code,
                name=achievement_def['name'],
                unlocked_date=datetime.utcnow(),
                value_json=json.dumps(value_context) if value_context else None
            )
            
            db.session.add(achievement)
            db.session.commit()
            return True
        
        return False
    
    @staticmethod
    def _check_achievement_criteria(session: ChargingSession, achievement_code: str) -> tuple[bool, Optional[Dict]]:
        """
        Check if a session meets the criteria for a specific achievement.
        Returns (criteria_met: bool, value_context: Optional[Dict])
        """
        if achievement_code == '1000kwh':
            # Check total kWh across all sessions for user
            total_kwh = db.session.query(func.sum(ChargingSession.charge_delivered_kwh)).filter_by(
                user_id=session.user_id
            ).scalar() or 0
            
            if total_kwh >= 1000:
                return True, {'value': f'{total_kwh:.0f} kWh total'}
        
        elif achievement_code == 'cheapest_mile':
            # Check if this is the user's cheapest cost per mile session for this car
            metrics = DerivedMetricsService.calculate_session_metrics(session, None)
            if metrics['cost_per_mile'] > 0 and metrics['efficiency_used']:
                
                # Find all sessions for this car with cost per mile
                car_sessions = ChargingSession.query.filter_by(
                    user_id=session.user_id,
                    car_id=session.car_id
                ).filter(ChargingSession.cost_per_kwh > 0).all()
                
                cheapest_cost_per_mile = float('inf')
                for s in car_sessions:
                    s_metrics = DerivedMetricsService.calculate_session_metrics(s, None)
                    if s_metrics['cost_per_mile'] > 0:
                        cheapest_cost_per_mile = min(cheapest_cost_per_mile, s_metrics['cost_per_mile'])
                
                if metrics['cost_per_mile'] == cheapest_cost_per_mile:
                    cost_pence = metrics['cost_per_mile'] * 100
                    return True, {'value': f'{cost_pence:.1f}p/mi'}
        
        elif achievement_code == 'fastest_session':
            # Check if this is the user's fastest average power session for this car
            if session.duration_mins > 0:
                avg_power = session.charge_delivered_kwh / (session.duration_mins / 60)
                
                # Find max power for this car
                max_power_query = db.session.query(
                    func.max(ChargingSession.charge_delivered_kwh / (ChargingSession.duration_mins / 60.0))
                ).filter_by(
                    user_id=session.user_id,
                    car_id=session.car_id
                ).filter(ChargingSession.duration_mins > 0)
                
                max_power = max_power_query.scalar() or 0
                
                if abs(avg_power - max_power) < 0.1:  # Account for floating point precision
                    return True, {'value': f'{avg_power:.1f} kW avg'}
        
        elif achievement_code == 'marathon_charge':
            # Check if session is longer than 8 hours
            if session.duration_mins >= 480:  # 8 hours = 480 minutes
                hours = session.duration_mins / 60
                return True, {'value': f'{hours:.1f} hours'}
        
        elif achievement_code == 'free_charge_finder':
            # Check if this is a free charging session
            if session.cost_per_kwh == 0:
                return True, {'value': f'{session.charge_delivered_kwh:.1f} kWh free'}
        
        elif achievement_code == 'night_owl':
            # Check if session was created between midnight and 6 AM
            if session.created_at:
                hour = session.created_at.hour
                if 0 <= hour < 6:
                    return True, {'value': f'{session.created_at.strftime("%H:%M")} charge'}
        
        elif achievement_code == 'efficiency_master':
            # Check if session achieved 5+ mi/kWh efficiency
            metrics = DerivedMetricsService.calculate_session_metrics(session, None)
            if metrics['efficiency_used'] is not None and metrics['efficiency_used'] >= 5.0:
                return True, {'value': f'{metrics["efficiency_used"]:.1f} mi/kWh'}
        
        elif achievement_code == 'road_warrior':
            # Check if user has 100+ sessions for this car
            session_count = ChargingSession.query.filter_by(
                user_id=session.user_id,
                car_id=session.car_id
            ).count()
            
            if session_count >= 100:
                return True, {'value': f'{session_count} sessions'}
        
        # New P6-6 achievements logic
        elif achievement_code == 'winter_warrior':
            # Check if ambient temp < 5°C
            if session.ambient_temp_c is not None and session.ambient_temp_c < 5.0:
                return True, {'value': f'{session.ambient_temp_c:.1f}°C braving the cold'}
        
        elif achievement_code == 'first_plug':
            # Check if this is the user's first session for this car
            first_session = ChargingSession.query.filter_by(
                user_id=session.user_id,
                car_id=session.car_id
            ).order_by(ChargingSession.date.asc()).first()
            
            if first_session and first_session.id == session.id:
                return True, {'value': 'Welcome to EV charging!'}
        
        elif achievement_code == 'road_to_10000':
            # Check total kWh across all sessions for user
            total_kwh = db.session.query(func.sum(ChargingSession.charge_delivered_kwh)).filter_by(
                user_id=session.user_id
            ).scalar() or 0
            
            if total_kwh >= 10000:
                return True, {'value': f'{total_kwh:.0f} kWh total'}
        
        elif achievement_code == 'century_session':
            # Check if user has 100+ sessions for this car
            session_count = ChargingSession.query.filter_by(
                user_id=session.user_id,
                car_id=session.car_id
            ).count()
            
            if session_count >= 100:
                return True, {'value': f'{session_count}th session'}
        
        elif achievement_code == 'penny_pincher':
            # Check if session cost < £1
            total_cost = session.charge_delivered_kwh * session.cost_per_kwh
            if total_cost < 1.0 and total_cost > 0:
                return True, {'value': f'£{total_cost:.2f} total'}
        
        elif achievement_code == 'savers_streak':
            # Check if last 7 sessions were below average cost/kWh
            # Get last 7 sessions for this car
            recent_sessions = ChargingSession.query.filter_by(
                user_id=session.user_id,
                car_id=session.car_id
            ).filter(ChargingSession.cost_per_kwh > 0).order_by(
                ChargingSession.date.desc()
            ).limit(7).all()
            
            if len(recent_sessions) >= 7:
                # Calculate average cost/kWh for this car
                avg_cost_kwh = db.session.query(func.avg(ChargingSession.cost_per_kwh)).filter_by(
                    user_id=session.user_id,
                    car_id=session.car_id
                ).filter(ChargingSession.cost_per_kwh > 0).scalar() or 0
                
                # Check if all 7 recent sessions are below average
                all_below_avg = all(s.cost_per_kwh < avg_cost_kwh for s in recent_sessions)
                if all_below_avg:
                    return True, {'value': f'7 sessions < {avg_cost_kwh:.2f}p/kWh avg'}
        
        elif achievement_code == 'off_peak_champ':
            # Check if most sessions are off-peak (between 10pm and 6am)
            all_sessions = ChargingSession.query.filter_by(
                user_id=session.user_id,
                car_id=session.car_id
            ).all()
            
            if len(all_sessions) >= 10:  # Need at least 10 sessions
                off_peak_count = 0
                for s in all_sessions:
                    if s.session_start:
                        hour = s.session_start.hour
                        if hour >= 22 or hour < 6:  # 10pm-6am
                            off_peak_count += 1
                
                off_peak_percentage = (off_peak_count / len(all_sessions)) * 100
                if off_peak_percentage >= 70:  # 70% or more off-peak
                    return True, {'value': f'{off_peak_percentage:.0f}% off-peak'}
        
        elif achievement_code == 'rapid_riser':
            # Check if session has >100kW average power
            if session.duration_mins > 0:
                avg_power = session.charge_delivered_kwh / (session.duration_mins / 60)
                if avg_power >= 100:
                    return True, {'value': f'{avg_power:.0f} kW average'}
        
        elif achievement_code == 'sprint_finish':
            # Check if 20-80% achieved in under 25 minutes
            soc_delta = session.soc_to - session.soc_from
            if (session.soc_from <= 25 and session.soc_to >= 75 and 
                soc_delta >= 55 and session.duration_mins <= 25):
                return True, {'value': f'{session.duration_mins:.0f} min for {soc_delta:.0f}%'}
        
        elif achievement_code == 'solar_soaker':
            # Check if session cost = £0 (same as free charge finder for now)
            if session.cost_per_kwh == 0:
                return True, {'value': f'{session.charge_delivered_kwh:.1f} kWh solar'}
        
        elif achievement_code == 'heatwave_hero':
            # Check if ambient temp > 30°C
            if session.ambient_temp_c is not None and session.ambient_temp_c > 30.0:
                return True, {'value': f'{session.ambient_temp_c:.1f}°C beating the heat'}
        
        elif achievement_code == 'forgotten_plug':
            # Check if session >12 hours but <5 kWh delivered
            if (session.duration_mins >= 720 and  # 12 hours = 720 minutes
                session.charge_delivered_kwh < 5.0):
                hours = session.duration_mins / 60
                return True, {'value': f'{hours:.1f}h for {session.charge_delivered_kwh:.1f} kWh'}
        
        elif achievement_code == 'range_anxiety':
            # Check if charge started <5% SoC
            if session.soc_from <= 5:
                return True, {'value': f'Started at {session.soc_from:.0f}%'}
        
        elif achievement_code == 'explorer':
            # Check if user has used 10+ different networks
            if session.charge_network:
                unique_networks = db.session.query(ChargingSession.charge_network).filter_by(
                    user_id=session.user_id
                ).filter(ChargingSession.charge_network.isnot(None)).distinct().count()
                
                if unique_networks >= 10:
                    return True, {'value': f'{unique_networks} networks'}
            return False, None
        
        elif achievement_code == 'staycationer':
            # Check if 90%+ of sessions are at home
            all_sessions = ChargingSession.query.filter_by(
                user_id=session.user_id,
                car_id=session.car_id
            ).all()
            
            if len(all_sessions) >= 10:  # Need at least 10 sessions
                home_count = sum(1 for s in all_sessions if DerivedMetricsService._is_home_like(s))
                home_percentage = (home_count / len(all_sessions)) * 100
                
                if home_percentage >= 90:
                    return True, {'value': f'{home_percentage:.0f}% at home'}
        
        return False, None
    
    @staticmethod
    def get_user_achievements(user_id: int, car_id: Optional[int] = None) -> Dict:
        """
        Get achievements status for a user, returning unlocked and locked achievements.
        Returns format expected by /api/achievements endpoint.
        """
        # Get unlocked achievements
        query = Achievement.query.filter_by(user_id=user_id)
        if car_id:
            query = query.filter(
                (Achievement.car_id == car_id) | (Achievement.car_id.is_(None))
            )
        
        unlocked_achievements = query.order_by(Achievement.unlocked_date.desc()).all()
        
        # Determine locked achievements
        unlocked_codes = {a.code for a in unlocked_achievements}
        locked_achievements = []
        
        for code, definition in AchievementEngine.ACHIEVEMENT_DEFINITIONS.items():
            if code not in unlocked_codes:
                # Check if this achievement is relevant for the car filter
                if car_id and not definition['global']:
                    # For car-specific achievements, only show if we're filtering by that car
                    locked_achievements.append({
                        'code': code,
                        'name': definition['name'],
                        'criteria': definition['description']
                    })
                elif not car_id or definition['global']:
                    # Show global achievements when not filtering, or when filtering but it's global
                    locked_achievements.append({
                        'code': code,
                        'name': definition['name'],
                        'criteria': definition['description']
                    })
        
        return {
            'unlocked': [a.to_dict() for a in unlocked_achievements],
            'locked': locked_achievements
        }
    
    @staticmethod
    def initialize_achievements_for_user(user_id: int) -> int:
        """
        Initialize/backfill achievements for an existing user.
        Returns count of newly awarded achievements.
        """
        return len(AchievementEngine.check_all_achievements_for_user(user_id))

