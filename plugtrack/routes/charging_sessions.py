from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user
from models.charging_session import ChargingSession, db
from models.car import Car
from services.forms import ChargingSessionForm
from services.reports import ReportsService
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
