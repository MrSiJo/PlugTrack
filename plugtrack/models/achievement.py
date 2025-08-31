from models.user import db
from datetime import datetime


class Achievement(db.Model):
    """Achievement/Badge tracking for gamification"""
    __tablename__ = 'achievement'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=True)  # Some achievements might be global
    code = db.Column(db.String(50), nullable=False)  # Unique identifier like '1000kwh', 'cheapest_mile'
    name = db.Column(db.String(100), nullable=False)  # Display name like "1000 kWh Club"
    unlocked_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    value_json = db.Column(db.Text, nullable=True)  # JSON context like {"value": "52 kW avg"}
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('idx_achievement_user_car_code', 'user_id', 'car_id', 'code'),
        db.Index('idx_achievement_user_code', 'user_id', 'code'),
        db.Index('idx_achievement_user_unlocked', 'user_id', 'unlocked_date'),
    )
    
    def __repr__(self):
        return f'<Achievement {self.code} for user {self.user_id}>'
    
    def to_dict(self):
        """Convert achievement to dictionary for API responses"""
        result = {
            'code': self.code,
            'name': self.name,
            'date': self.unlocked_date.isoformat() if self.unlocked_date else None
        }
        
        # Add value if present
        if self.value_json:
            import json
            try:
                value_data = json.loads(self.value_json)
                if 'value' in value_data:
                    result['value'] = value_data['value']
            except (json.JSONDecodeError, TypeError):
                pass
        
        return result

