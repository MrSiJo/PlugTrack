from .user import db

class Settings(db.Model):
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=True)
    encrypted = db.Column(db.Boolean, default=False)
    
    # Composite unique constraint
    __table_args__ = (db.UniqueConstraint('user_id', 'key', name='_user_key_uc'),)
    
    def __repr__(self):
        return f'<Settings {self.key}={self.value}>'
    
    @classmethod
    def get_setting(cls, user_id, key, default=None):
        """Get a setting value for a user"""
        setting = cls.query.filter_by(user_id=user_id, key=key).first()
        return setting.value if setting else default
    
    @classmethod
    def set_setting(cls, user_id, key, value, encrypted=False):
        """Set a setting value for a user"""
        setting = cls.query.filter_by(user_id=user_id, key=key).first()
        if setting:
            setting.value = value
            setting.encrypted = encrypted
        else:
            setting = cls(user_id=user_id, key=key, value=value, encrypted=encrypted)
            db.session.add(setting)
        db.session.commit()
        return setting
