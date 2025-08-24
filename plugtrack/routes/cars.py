from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from ..models.car import Car, db
from ..services.forms import CarForm

cars_bp = Blueprint('cars', __name__)

@cars_bp.route('/cars')
@login_required
def index():
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.active.desc(), Car.make, Car.model).all()
    return render_template('cars/index.html', cars=cars)

@cars_bp.route('/cars/new', methods=['GET', 'POST'])
@login_required
def new():
    form = CarForm()
    if form.validate_on_submit():
        car = Car(
            user_id=current_user.id,
            make=form.make.data,
            model=form.model.data,
            battery_kwh=form.battery_kwh.data,
            efficiency_mpkwh=form.efficiency_mpkwh.data,
            active=form.active.data,
            recommended_full_charge_enabled=form.recommended_full_charge_enabled.data,
            recommended_full_charge_frequency_value=form.recommended_full_charge_frequency_value.data,
            recommended_full_charge_frequency_unit=form.recommended_full_charge_frequency_unit.data
        )
        db.session.add(car)
        db.session.commit()
        flash('Car added successfully!', 'success')
        return redirect(url_for('cars.index'))
    
    return render_template('cars/new.html', form=form, title='Add New Car')

@cars_bp.route('/cars/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    car = Car.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    form = CarForm(obj=car)
    
    if form.validate_on_submit():
        car.make = form.make.data
        car.model = form.model.data
        car.battery_kwh = form.battery_kwh.data
        car.efficiency_mpkwh = form.efficiency_mpkwh.data
        car.active = form.active.data
        car.recommended_full_charge_enabled = form.recommended_full_charge_enabled.data
        car.recommended_full_charge_frequency_value = form.recommended_full_charge_frequency_value.data
        car.recommended_full_charge_frequency_unit = form.recommended_full_charge_frequency_unit.data
        
        db.session.commit()
        flash('Car updated successfully!', 'success')
        return redirect(url_for('cars.index'))
    
    return render_template('cars/edit.html', form=form, car=car, title='Edit Car')

@cars_bp.route('/cars/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    car = Car.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(car)
    db.session.commit()
    flash('Car deleted successfully!', 'success')
    return redirect(url_for('cars.index'))
