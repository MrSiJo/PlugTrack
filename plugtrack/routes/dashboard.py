from flask import Blueprint, render_template
from flask_login import login_required, current_user
from ..models.car import Car
from ..models.charging_session import ChargingSession

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@login_required
def index():
    # Get active car
    active_car = Car.query.filter_by(user_id=current_user.id, active=True).first()
    
    # Get last 5 charging sessions
    recent_sessions = ChargingSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChargingSession.date.desc(), ChargingSession.created_at.desc())\
        .limit(5).all()
    
    # Calculate some basic stats
    total_sessions = ChargingSession.query.filter_by(user_id=current_user.id).count()
    total_kwh = sum(session.charge_delivered_kwh for session in recent_sessions)
    total_cost = sum(session.total_cost for session in recent_sessions)
    
    return render_template('dashboard/index.html',
                         active_car=active_car,
                         recent_sessions=recent_sessions,
                         total_sessions=total_sessions,
                         total_kwh=total_kwh,
                         total_cost=total_cost)
