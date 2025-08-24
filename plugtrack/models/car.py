from .user import db
from datetime import datetime

class Car(db.Model):
    __tablename__ = 'car'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    make = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    battery_kwh = db.Column(db.Float, nullable=False)
    efficiency_mpkwh = db.Column(db.Float, nullable=True)  # miles per kWh
    active = db.Column(db.Boolean, default=True)
    recommended_full_charge_enabled = db.Column(db.Boolean, default=False)
    recommended_full_charge_frequency_value = db.Column(db.Integer, nullable=True)
    recommended_full_charge_frequency_unit = db.Column(db.String(10), nullable=True)  # 'days' or 'months'
    
    # Relationships
    charging_sessions = db.relationship('ChargingSession', backref='car', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Car {self.make} {self.model}>'
    
    @property
    def display_name(self):
        return f"{self.make} {self.model}"
    
    @property
    def frequency_display(self):
        if not self.recommended_full_charge_enabled:
            return "Disabled"
        if self.recommended_full_charge_frequency_value and self.recommended_full_charge_frequency_unit:
            return f"Every {self.recommended_full_charge_frequency_value} {self.recommended_full_charge_frequency_unit}"
        return "Not set"
