from models.charging_session import ChargingSession, db
from models.car import Car

class BaselineManager:
    """Service for managing baseline charging sessions per car"""
    
    @staticmethod
    def ensure_baseline_for_car(user_id, car_id):
        """
        Ensures exactly one session per car is marked as baseline.
        Automatically assigns the earliest session as baseline.
        """
        # Clear any existing baseline flags for this car
        ChargingSession.query.filter_by(
            user_id=user_id, 
            car_id=car_id, 
            is_baseline=True
        ).update({"is_baseline": False})
        db.session.flush()
        
        # Find the earliest session for this car
        first_session = (ChargingSession.query
                        .filter_by(user_id=user_id, car_id=car_id)
                        .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
                        .first())
        
        if first_session:
            first_session.is_baseline = True
            db.session.commit()
            return first_session
        
        return None
    
    @staticmethod
    def get_baseline_session(user_id, car_id):
        """Get the baseline session for a specific car"""
        return ChargingSession.query.filter_by(
            user_id=user_id,
            car_id=car_id,
            is_baseline=True
        ).first()
    
    @staticmethod
    def is_baseline_session(session):
        """Check if a session is marked as baseline"""
        return session.is_baseline if hasattr(session, 'is_baseline') else False
    
    @staticmethod
    def get_first_usable_session(user_id, car_id):
        """Get the first non-baseline session for efficiency calculations"""
        return (ChargingSession.query
                .filter_by(user_id=user_id, car_id=car_id)
                .filter(ChargingSession.is_baseline == False)
                .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
                .first())
    
    @staticmethod
    def initialize_all_baselines(user_id):
        """Initialize baseline sessions for all cars owned by a user"""
        cars = Car.query.filter_by(user_id=user_id).all()
        for car in cars:
            BaselineManager.ensure_baseline_for_car(user_id, car.id)
