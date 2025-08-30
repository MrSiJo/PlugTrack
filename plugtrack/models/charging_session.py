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
    venue_type = db.Column(db.String(20), nullable=True)  # 'home' or 'public' - optional for Phase 3
    is_baseline = db.Column(db.Boolean, default=False, nullable=False)  # Marks earliest session per car
    ambient_temp_c = db.Column(db.Float, nullable=True)  # Ambient temperature in Celsius
    preconditioning_used = db.Column(db.Boolean, nullable=True)  # Whether preconditioning was used (NULL=Unknown, 0=No, 1=Yes)
    preconditioning_events = db.Column(db.Integer, nullable=True)  # Number of preconditioning events
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
    
    @property
    def is_home_charging(self):
        """Detect if this is home charging based on venue_type or location_label"""
        if self.venue_type:
            return self.venue_type.lower() == 'home'
        
        # Fallback to location-based detection
        try:
            from models.settings import Settings
            home_aliases = Settings.get_setting(self.user_id, 'home_aliases_csv', 'home,house,garage')
            aliases = [alias.strip().lower() for alias in home_aliases.split(',')]
            return any(alias in self.location_label.lower() for alias in aliases)
        except:
            # Fallback to simple detection if settings not available
            return 'home' in self.location_label.lower() or 'garage' in self.location_label.lower()
