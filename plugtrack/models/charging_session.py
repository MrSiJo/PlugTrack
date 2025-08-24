from models.user import db
from datetime import datetime

class ChargingSession(db.Model):
    __tablename__ = 'charging_session'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    odometer = db.Column(db.Integer, nullable=False)
    charge_type = db.Column(db.String(10), nullable=False)  # 'AC' or 'DC'
    charge_speed_kw = db.Column(db.Float, nullable=False)
    location_label = db.Column(db.String(200), nullable=False)
    charge_network = db.Column(db.String(100), nullable=True)
    charge_delivered_kwh = db.Column(db.Float, nullable=False)
    duration_mins = db.Column(db.Integer, nullable=False)
    cost_per_kwh = db.Column(db.Float, nullable=False)
    soc_from = db.Column(db.Integer, nullable=False)  # State of Charge percentage
    soc_to = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ChargingSession {self.date} - {self.charge_delivered_kwh}kWh>'
    
    @property
    def total_cost(self):
        return self.charge_delivered_kwh * self.cost_per_kwh
    
    @property
    def soc_range(self):
        return f"{self.soc_from}% → {self.soc_to}%"
    
    @property
    def duration_hours(self):
        return self.duration_mins / 60.0
    
    @property
    def average_power_kw(self):
        if self.duration_hours > 0:
            return self.charge_delivered_kwh / self.duration_hours
        return 0
