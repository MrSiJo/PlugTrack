from flask import Blueprint, render_template, redirect, url_for, flash, request, Response, jsonify
from flask_login import login_required, current_user
from models.charging_session import ChargingSession, db
from models.car import Car
from services.forms import ChargingSessionForm
from services.reports import ReportsService
from services.derived_metrics import DerivedMetricsService
from services.hints import HintsService
from datetime import datetime, timedelta

charging_sessions_bp = Blueprint('charging_sessions', __name__)

@charging_sessions_bp.route('/charging-sessions')
@login_required
def index():
    """Charging sessions index page"""
    # Get filter parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    charge_type = request.args.get('charge_type')
    charge_network = request.args.get('charge_network')
    
    # Build query
    query = ChargingSession.query.filter_by(user_id=current_user.id)
    
    # Apply filters
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(ChargingSession.date >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(ChargingSession.date <= date_to_obj)
        except ValueError:
            pass
    
    if car_id:
        query = query.filter_by(car_id=car_id)
    
    if charge_type:
        query = query.filter_by(charge_type=charge_type)
    
    if charge_network:
        query = query.filter(ChargingSession.charge_network.ilike(f'%{charge_network}%'))
    
    # Order by date (newest first)
    sessions = query.order_by(ChargingSession.date.desc(), ChargingSession.created_at.desc()).all()
    
    # Get filter options
    cars = Car.query.filter_by(user_id=current_user.id).all()
    charge_types = ['AC', 'DC']
    networks = db.session.query(ChargingSession.charge_network)\
        .filter(ChargingSession.charge_network.isnot(None))\
        .distinct()\
        .all()
    networks = [n[0] for n in networks if n[0]]
    
    return render_template('charging_sessions/index.html',
                         sessions=sessions,
                         cars=cars,
                         charge_types=charge_types,
                         networks=networks,
                         date_from=date_from,
                         date_to=date_to,
                         selected_car_id=car_id,
                         selected_charge_type=charge_type,
                         selected_network=charge_network)

@charging_sessions_bp.route('/charging-sessions/new', methods=['GET', 'POST'])
@login_required
def new():
    """Add new charging session"""
    form = ChargingSessionForm()
    
    # Populate car choices
    form.car_id.choices = [(car.id, car.display_name) for car in Car.query.filter_by(user_id=current_user.id).all()]
    
    if form.validate_on_submit():
        session = ChargingSession(
            user_id=current_user.id,
            car_id=form.car_id.data,
            date=form.date.data,
            odometer=form.odometer.data,
            charge_type=form.charge_type.data,
            charge_speed_kw=form.charge_speed_kw.data,
            location_label=form.location_label.data,
            charge_network=form.charge_network.data,
            charge_delivered_kwh=form.charge_delivered_kwh.data,
            duration_mins=form.duration_mins.data,
            cost_per_kwh=form.cost_per_kwh.data,
            soc_from=form.soc_from.data,
            soc_to=form.soc_to.data,
            notes=form.notes.data
        )
        
        db.session.add(session)
        db.session.commit()
        flash('Charging session added successfully!', 'success')
        return redirect(url_for('charging_sessions.index'))
    
    return render_template('charging_sessions/new.html', form=form, title='Add Charging Session')

@charging_sessions_bp.route('/charging-sessions/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    """Edit charging session"""
    session = ChargingSession.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    form = ChargingSessionForm(obj=session)
    
    # Populate car choices
    form.car_id.choices = [(car.id, car.display_name) for car in Car.query.filter_by(user_id=current_user.id).all()]
    
    if form.validate_on_submit():
        session.car_id = form.car_id.data
        session.date = form.date.data
        session.odometer = form.odometer.data
        session.charge_type = form.charge_type.data
        session.charge_speed_kw = form.charge_speed_kw.data
        session.location_label = form.location_label.data
        session.charge_network = form.charge_network.data
        session.charge_delivered_kwh = form.charge_delivered_kwh.data
        session.duration_mins = form.duration_mins.data
        session.cost_per_kwh = form.cost_per_kwh.data
        session.soc_from = form.soc_from.data
        session.soc_to = form.soc_to.data
        session.notes = form.notes.data
        
        db.session.commit()
        flash('Charging session updated successfully!', 'success')
        return redirect(url_for('charging_sessions.index'))
    
    return render_template('charging_sessions/edit.html', form=form, session=session, title='Edit Charging Session')

@charging_sessions_bp.route('/charging-sessions/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    """Delete charging session"""
    session = ChargingSession.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(session)
    db.session.commit()
    flash('Charging session deleted successfully!', 'success')
    return redirect(url_for('charging_sessions.index'))

@charging_sessions_bp.route('/charging-sessions/export')
@login_required
def export():
    """Export charging sessions to CSV"""
    # Get filter parameters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    car_id = request.args.get('car_id')
    charge_type = request.args.get('charge_type')
    charge_network = request.args.get('charge_network')
    
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
        car_id=car_id,
        charge_type=charge_type,
        charge_network=charge_network
    )
    
    # Generate filename
    filename = ReportsService.get_export_filename(
        date_from=date_from,
        date_to=date_to,
        car_id=car_id
    )
    
    return Response(csv_data, mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename={filename}'})

@charging_sessions_bp.route('/charging-sessions/<int:id>/details')
@login_required
def details(id):
    """Get detailed session information for the detail drawer"""
    session = ChargingSession.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    car = Car.query.get(session.car_id)
    
    # Get derived metrics
    metrics = DerivedMetricsService.calculate_session_metrics(session, car)
    
    # Get similar sessions for comparison
    similar_sessions = DerivedMetricsService.get_similar_sessions(session, limit=3)
    
    # Get rolling averages
    rolling_avgs = DerivedMetricsService.get_rolling_averages(session.user_id, session.car_id, days=30)
    
    # Get hints
    hints = HintsService.get_session_hints(session, car)
    
    # Calculate deltas vs similar sessions
    deltas = {}
    if similar_sessions:
        last_similar = similar_sessions[0]
        last_similar_metrics = DerivedMetricsService.calculate_session_metrics(last_similar, car)
        
        deltas['vs_last_similar'] = {
            'cost_per_mile_delta': metrics['cost_per_mile'] - last_similar_metrics['cost_per_mile'],
            'avg_power_kw_delta': metrics['avg_power_kw'] - last_similar_metrics['avg_power_kw'],
            'percent_per_kwh_delta': metrics['percent_per_kwh'] - last_similar_metrics['percent_per_kwh']
        }
    
    # Calculate deltas vs rolling averages
    if rolling_avgs['avg_cost_per_mile'] > 0:
        deltas['vs_30_day_avg'] = {
            'cost_per_mile_delta': metrics['cost_per_mile'] - rolling_avgs['avg_cost_per_mile'],
            'avg_power_kw_delta': metrics['avg_power_kw'] - rolling_avgs['avg_power_kw']
        }
    
    return jsonify({
        'session': {
            'id': session.id,
            'date': session.date.strftime('%Y-%m-%d'),
            'car_name': car.display_name if car else 'Unknown Car',
            'charge_type': session.charge_type,
            'location': session.location_label,
            'network': session.charge_network,
            'notes': session.notes
        },
        'metrics': metrics,
        'deltas': deltas,
        'hints': hints,
        'rolling_averages': rolling_avgs
    })

@charging_sessions_bp.route('/charging-sessions/<int:id>/dismiss-hint', methods=['POST'])
@login_required
def dismiss_hint(id):
    """Dismiss a hint for a session"""
    session = ChargingSession.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    hint_code = data.get('hint_code')
    
    if not hint_code:
        return jsonify({'error': 'Hint code required'}), 400
    
    HintsService.dismiss_hint(session.id, hint_code)
    return jsonify({'success': True})
