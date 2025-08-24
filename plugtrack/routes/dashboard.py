from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models.car import Car
from models.charging_session import ChargingSession
from services.derived_metrics import DerivedMetricsService
from datetime import datetime, timedelta

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@login_required
def index():
    """Dashboard index page"""
    # Get filter parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    
    # Convert date strings to datetime objects
    if date_from:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
    else:
        date_from = (datetime.now() - timedelta(days=30)).date()
    
    if date_to:
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
    else:
        date_to = datetime.now().date()
    
    # Get any available car for recommendations and default selection
    available_car = Car.query.filter_by(user_id=current_user.id).first()
    
    # Get metrics and recommendations
    metrics = DerivedMetricsService.get_dashboard_metrics(
        current_user.id, 
        date_from=date_from, 
        date_to=date_to, 
        car_id=car_id
    )
    
    # Get recommendations
    recommendations = DerivedMetricsService.get_recommendations(current_user.id, available_car)
    
    # Get efficiency information
    efficiency_info = DerivedMetricsService.get_current_efficiency_info(current_user.id, car_id)
    
    # Get recent charging sessions for display
    recent_sessions = ChargingSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChargingSession.date.desc(), ChargingSession.created_at.desc())\
        .limit(5).all()
    
    # Get cars for filter dropdown
    cars = Car.query.filter_by(user_id=current_user.id).all()
    
    return render_template('dashboard/index.html',
                         metrics=metrics,
                         recommendations=recommendations,
                         efficiency_info=efficiency_info,
                         recent_sessions=recent_sessions,
                         cars=cars,
                         date_from=date_from,
                         date_to=date_to,
                         selected_car=Car.query.get(car_id) if car_id else available_car)
