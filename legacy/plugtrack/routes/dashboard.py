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
    
    # Phase 5.1: Get battery hygiene and location leaderboard data
    from services.insights import InsightsService
    battery_hygiene = InsightsService.get_battery_hygiene_metrics(current_user.id, car_id, days=30)
    location_leaderboard = InsightsService.get_location_leaderboard(current_user.id, car_id, limit=5)
    
    # Get cars for filter dropdown FIRST (before using in reminder logic)
    cars = Car.query.filter_by(user_id=current_user.id).all()
    
    # Phase 5.4: Get reminder data
    from services.reminders import ReminderService
    reminder_data = ReminderService.check_full_charge_due(current_user.id, car_id)
    reminders = reminder_data.get('reminders', [])
    
    # P6-4: Get analytics summary for lifetime totals and cost extremes
    from services.analytics_agg import AnalyticsAggService
    analytics_summary = AnalyticsAggService.get_analytics_summary(current_user.id, car_id)
    
    # Check if any cars have reminder guidance enabled (for UI conditional display)
    has_reminder_guidance = any(
        car.recommended_full_charge_enabled and 
        car.recommended_full_charge_frequency_value and 
        car.recommended_full_charge_frequency_unit
        for car in cars
    )
    
    # Get recent charging sessions for display
    recent_sessions = ChargingSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChargingSession.date.desc(), ChargingSession.created_at.desc())\
        .limit(5).all()
    
    return render_template('dashboard/index.html',
                         metrics=metrics,
                         recommendations=recommendations,
                         efficiency_info=efficiency_info,
                         battery_hygiene=battery_hygiene,
                         location_leaderboard=location_leaderboard,
                         reminders=reminders,
                         has_reminder_guidance=has_reminder_guidance,
                         recent_sessions=recent_sessions,
                         cars=cars,
                         analytics_summary=analytics_summary,
                         date_from=date_from,
                         date_to=date_to,
                         selected_car=Car.query.get(car_id) if car_id else available_car)
