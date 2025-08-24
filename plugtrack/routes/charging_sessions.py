from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models.charging_session import ChargingSession, db
from models.car import Car
from services.forms import ChargingSessionForm
from datetime import datetime
import csv
from io import StringIO

charging_sessions_bp = Blueprint('charging_sessions', __name__)

@charging_sessions_bp.route('/charging-sessions')
@login_required
def index():
    sessions = ChargingSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChargingSession.date.desc(), ChargingSession.created_at.desc()).all()
    return render_template('charging_sessions/index.html', sessions=sessions)

@charging_sessions_bp.route('/charging-sessions/new', methods=['GET', 'POST'])
@login_required
def new():
    form = ChargingSessionForm()
    # Populate car choices
    form.car_id.choices = [(car.id, car.display_name) for car in Car.query.filter_by(user_id=current_user.id, active=True).all()]
    
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
    session = ChargingSession.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    form = ChargingSessionForm(obj=session)
    
    # Populate car choices
    form.car_id.choices = [(car.id, car.display_name) for car in Car.query.filter_by(user_id=current_user.id, active=True).all()]
    
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
    session = ChargingSession.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(session)
    db.session.commit()
    flash('Charging session deleted successfully!', 'success')
    return redirect(url_for('charging_sessions.index'))

@charging_sessions_bp.route('/charging-sessions/export')
@login_required
def export():
    sessions = ChargingSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChargingSession.date.desc()).all()
    
    # Create CSV data
    si = StringIO()
    cw = csv.writer(si)
    
    # Write header
    cw.writerow(['Date', 'Car', 'Odometer', 'Type', 'Speed (kW)', 'Location', 'Network', 
                 'kWh Delivered', 'Duration (mins)', 'Cost/kWh', 'SoC From', 'SoC To', 'Notes'])
    
    # Write data
    for session in sessions:
        car = Car.query.get(session.car_id)
        cw.writerow([
            session.date.strftime('%Y-%m-%d'),
            car.display_name if car else 'Unknown',
            session.odometer,
            session.charge_type,
            session.charge_speed_kw,
            session.location_label,
            session.charge_network or '',
            session.charge_delivered_kwh,
            session.duration_mins,
            session.cost_per_kwh,
            session.soc_from,
            session.soc_to,
            session.notes or ''
        ])
    
    output = si.getvalue()
    si.close()
    
    from flask import Response
    return Response(output, mimetype='text/csv', 
                   headers={'Content-Disposition': 'attachment; filename=charging_sessions.csv'})
