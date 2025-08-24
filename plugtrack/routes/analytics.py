from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required, current_user
from models.car import Car
from services.derived_metrics import DerivedMetricsService
from services.reports import ReportsService
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
                         selected_car=Car.query.get(car_id) if car_id else None)

@analytics_bp.route('/api/chart-data')
@login_required
def chart_data():
    """API endpoint to return chart data as JSON"""
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    
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
