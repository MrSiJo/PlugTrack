from models.user import db

class SessionMeta(db.Model):
    __tablename__ = 'session_meta'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('charging_session.id', ondelete='CASCADE'), nullable=False)
    key = db.Column(db.Text, nullable=False)
    value = db.Column(db.Text, nullable=False)
    
    # Composite unique constraint
    __table_args__ = (db.UniqueConstraint('session_id', 'key', name='_session_key_uc'),)
    
    def __repr__(self):
        return f'<SessionMeta {self.session_id}:{self.key}={self.value}>'
    
    @classmethod
    def get_meta(cls, session_id, key, default=None):
        """Get metadata value for a session"""
        meta = cls.query.filter_by(session_id=session_id, key=key).first()
        return meta.value if meta else default
    
    @classmethod
    def set_meta(cls, session_id, key, value):
        """Set metadata value for a session"""
        meta = cls.query.filter_by(session_id=session_id, key=key).first()
        if meta:
            meta.value = value
        else:
            meta = cls(session_id=session_id, key=key, value=value)
            db.session.add(meta)
        db.session.commit()
        return meta
    
    @classmethod
    def delete_meta(cls, session_id, key):
        """Delete metadata for a session"""
        meta = cls.query.filter_by(session_id=session_id, key=key).first()
        if meta:
            db.session.delete(meta)
            db.session.commit()
            return True
        return False
