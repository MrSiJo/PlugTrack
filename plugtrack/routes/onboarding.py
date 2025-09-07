"""
Onboarding routes for first-run user setup.
Handles the initial user creation and optional car setup flow.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, current_user
from services.onboarding import OnboardingService
from services.forms import OnboardingUserForm, OnboardingCarForm
from models.user import User

onboarding_bp = Blueprint('onboarding', __name__, url_prefix='/onboarding')


@onboarding_bp.before_request
def check_onboarding_guard():
    """
    Guard to ensure onboarding routes are only accessible during first run.
    Redirects to dashboard if users already exist.
    """
    # Allow access to done page even if user is authenticated (part of onboarding flow)
    if request.endpoint == 'onboarding.done':
        return None
    
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if not OnboardingService.is_first_run():
        return redirect(url_for('auth.login'))


@onboarding_bp.route('/welcome')
def welcome():
    """Welcome page for first-time users."""
    # Ensure database tables exist
    try:
        from models.user import db
        db.create_all()
    except Exception as e:
        flash(f'Database initialization error: {str(e)}', 'error')
    
    return render_template('onboarding/welcome.html', title='Welcome to PlugTrack')


@onboarding_bp.route('/create-user', methods=['GET', 'POST'])
def create_user():
    """Create the initial user account."""
    # Ensure database tables exist before creating user
    try:
        from models.user import db
        db.create_all()
    except Exception as e:
        flash(f'Database initialization error: {str(e)}', 'error')
        return render_template('onboarding/create_user.html', title='Create Your Account', form=OnboardingUserForm())
    
    form = OnboardingUserForm()
    
    if form.validate_on_submit():
        result = OnboardingService.create_initial_user(
            username=form.username.data,
            password=form.password.data
        )
        
        if result['success']:
            # Log in the newly created user
            user = User.query.get(result['user']['id'])
            login_user(user)
            
            flash('Account created successfully! Welcome to PlugTrack!', 'success')
            return redirect(url_for('onboarding.create_car'))
        else:
            flash(result['error'], 'error')
    
    return render_template('onboarding/create_user.html', title='Create Your Account', form=form)


@onboarding_bp.route('/create-car', methods=['GET', 'POST'])
def create_car():
    """Optionally create the first car."""
    if not current_user.is_authenticated:
        return redirect(url_for('onboarding.welcome'))
    
    form = OnboardingCarForm()
    
    if form.validate_on_submit():
        # Check if any car data was provided
        has_car_data = any([
            form.make.data and form.make.data.strip(),
            form.model.data and form.model.data.strip(),
            form.battery_kwh.data
        ])
        
        if has_car_data:
            result = OnboardingService.optionally_create_first_car(
                user_id=current_user.id,
                make=form.make.data,
                model=form.model.data,
                battery_kwh=form.battery_kwh.data,
                efficiency_mpkwh=form.efficiency_mpkwh.data
            )
            
            if result['success']:
                if result['car']:
                    flash('Car added successfully! You can add more cars later.', 'success')
                else:
                    flash('No car data provided. You can add cars later from the Cars page.', 'info')
            else:
                flash(result['error'], 'error')
                return render_template('onboarding/create_car.html', title='Add Your First Car', form=form)
        else:
            flash('No car data provided. You can add cars later from the Cars page.', 'info')
        
        # Redirect to done page after car setup (or skip)
        return redirect(url_for('onboarding.done'))
    
    return render_template('onboarding/create_car.html', title='Add Your First Car', form=form)


@onboarding_bp.route('/skip-car')
def skip_car():
    """Skip car creation and go to done page."""
    if not current_user.is_authenticated:
        return redirect(url_for('onboarding.welcome'))
    
    flash('You can add cars later from the Cars page.', 'info')
    return redirect(url_for('onboarding.done'))


@onboarding_bp.route('/done')
def done():
    """Onboarding completion page."""
    if not current_user.is_authenticated:
        return redirect(url_for('onboarding.welcome'))
    
    return render_template('onboarding/done.html', title='Setup Complete')


@onboarding_bp.route('/status')
def status():
    """API endpoint to check onboarding status (for debugging)."""
    status_data = OnboardingService.get_onboarding_status()
    return jsonify(status_data)
