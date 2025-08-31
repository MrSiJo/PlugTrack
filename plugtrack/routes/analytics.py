from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required, current_user
from models.car import Car
from services.derived_metrics import DerivedMetricsService
from services.reports import ReportsService
from services.analytics_agg import AnalyticsAggService
from services.achievement_engine import AchievementEngine
from services.reminders import ReminderService
from services.reminders_api import RemindersApiService
from datetime import datetime, timedelta

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/analytics')
@login_required
def index():
    """Analytics dashboard page"""
    # Get filter parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    exclude_preconditioning = request.args.get('exclude_preconditioning') == 'true'
    
    # Convert date strings to datetime objects
    if date_from:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
    else:
        date_from = (datetime.now() - timedelta(days=30)).date()
    
    if date_to:
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
    else:
        date_to = datetime.now().date()
    
    # Get active car for recommendations
    active_car = Car.query.filter_by(user_id=current_user.id, active=True).first()
    
    # Get metrics and recommendations
    metrics = DerivedMetricsService.get_dashboard_metrics(
        current_user.id, 
        date_from=date_from, 
        date_to=date_to, 
        car_id=car_id
    )
    
    recommendations = DerivedMetricsService.get_recommendations(current_user.id, active_car)
    
    # Get chart data
    chart_data = DerivedMetricsService.get_chart_data(
        current_user.id, 
        date_from=date_from, 
        date_to=date_to, 
        car_id=car_id
    )
    
    # Get efficiency information
    efficiency_info = DerivedMetricsService.get_current_efficiency_info(current_user.id, car_id)
    
    # Get cars for filter dropdown
    cars = Car.query.filter_by(user_id=current_user.id).all()
    
    return render_template('analytics/index.html',
                         metrics=metrics,
                         recommendations=recommendations,
                         efficiency_info=efficiency_info,
                         chart_data=chart_data,
                         cars=cars,
                         date_from=date_from,
                         date_to=date_to,
                         selected_car=Car.query.get(car_id) if car_id else None,
                         exclude_preconditioning=exclude_preconditioning)

@analytics_bp.route('/api/chart-data')
@login_required
def chart_data():
    """API endpoint to return chart data as JSON"""
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    exclude_preconditioning = request.args.get('exclude_preconditioning') == 'true'
    
    # Convert date strings to datetime objects
    if date_from:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
    if date_to:
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
    
    chart_data = DerivedMetricsService.get_chart_data(
        current_user.id,
        date_from=date_from,
        date_to=date_to,
        car_id=car_id
    )
    
    return jsonify(chart_data)

@analytics_bp.route('/api/metrics')
@login_required
def metrics():
    """API endpoint to return dashboard metrics as JSON"""
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    
    # Convert date strings to datetime objects
    if date_from:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
    if date_to:
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
    
    metrics = DerivedMetricsService.get_dashboard_metrics(
        current_user.id,
        date_from=date_from,
        date_to=date_to,
        car_id=car_id
    )
    
    return jsonify(metrics)

@analytics_bp.route('/analytics/export')
@login_required
def export():
    """Export analytics data to CSV"""
    # Get filter parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    
    # Convert date strings to datetime objects
    if date_from:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
    if date_to:
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
    
    # Get CSV data
    csv_data = ReportsService.export_sessions_csv(
        current_user.id,
        date_from=date_from,
        date_to=date_to,
        car_id=car_id
    )
    
    # Generate filename
    filename = ReportsService.get_export_filename(
        date_from=date_from,
        date_to=date_to,
        car_id=car_id
    )
    
    return Response(csv_data, mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename={filename}'})

# Phase 6 Stage A: Aggregated Analytics API
@analytics_bp.route('/api/analytics/summary')
@login_required
def analytics_summary():
    """API endpoint for lightweight JSON summaries for dashboards"""
    car_id = request.args.get('car_id', type=int)
    
    summary = AnalyticsAggService.get_analytics_summary(current_user.id, car_id)
    return jsonify(summary)

# Phase 6 Stage B: Seasonal & Leaderboards
@analytics_bp.route('/api/analytics/seasonal')
@login_required
def analytics_seasonal():
    """API endpoint for efficiency vs ambient temperature bins"""
    car_id = request.args.get('car_id', type=int)
    
    seasonal_data = AnalyticsAggService.get_seasonal_analytics(current_user.id, car_id)
    return jsonify(seasonal_data)

@analytics_bp.route('/api/analytics/leaderboard')
@login_required
def analytics_leaderboard():
    """API endpoint for per-location metrics (median p/mi, p/kWh, session counts)"""
    car_id = request.args.get('car_id', type=int)
    
    leaderboard_data = AnalyticsAggService.get_leaderboard_analytics(current_user.id, car_id)
    return jsonify(leaderboard_data)

@analytics_bp.route('/api/analytics/sweetspot')
@login_required
def analytics_sweetspot():
    """API endpoint for SoC window efficiencies"""
    car_id = request.args.get('car_id', type=int)
    
    sweetspot_data = AnalyticsAggService.get_sweetspot_analytics(current_user.id, car_id)
    return jsonify(sweetspot_data)

# Phase 6 Stage C: Achievements & Gamification
@analytics_bp.route('/api/achievements')
@login_required
def achievements():
    """API endpoint for achievements/badges - returns unlocked + locked achievements"""
    car_id = request.args.get('car_id', type=int)
    
    achievements_data = AchievementEngine.get_user_achievements(current_user.id, car_id)
    return jsonify(achievements_data)

# Phase 6 Stage D: Reminders API
@analytics_bp.route('/api/reminders')
@login_required
def reminders():
    """API endpoint for reminders - returns due and upcoming reminder checks"""
    car_id = request.args.get('car_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    # Parse date parameters
    date_from_obj = None
    date_to_obj = None
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    reminders_data = RemindersApiService.get_reminders_api(
        current_user.id, car_id, date_from_obj, date_to_obj
    )
    return jsonify(reminders_data)
