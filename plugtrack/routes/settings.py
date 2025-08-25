from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from models.user import db
from models.settings import Settings
from services.forms import HomeChargingRateForm, HomeChargingSettingsForm, EfficiencySettingsForm, PetrolComparisonForm
from services.encryption import EncryptionService
from datetime import datetime

settings_bp = Blueprint('settings', __name__)

def get_currency_info():
    """Get current currency settings for the user"""
    # Default to GBP if no setting found
    currency_setting = Settings.get_setting(current_user.id, 'currency', 'GBP')
    
    currency_symbols = {
        'GBP': '£',
        'EUR': '€',
        'USD': '$'
    }
    
    return {
        'current_currency': currency_setting,
        'current_currency_symbol': currency_symbols.get(currency_setting, '£')
    }

def get_phase3_settings():
    """Get current Phase 3 settings for the user"""
    return {
        'home_charging_speed_kw': Settings.get_setting(current_user.id, 'home_charging_speed_kw', '7.4'),
        'home_aliases_csv': Settings.get_setting(current_user.id, 'home_aliases_csv', 'home,house,garage'),
        'default_efficiency_mpkwh': Settings.get_setting(current_user.id, 'default_efficiency_mpkwh', '3.7'),
        'petrol_price_p_per_litre': Settings.get_setting(current_user.id, 'petrol_price_p_per_litre', '128.9'),
        'petrol_mpg': Settings.get_setting(current_user.id, 'petrol_mpg', '60.0')
    }

from utils.petrol_calculations import calculate_petrol_threshold_p_per_kwh

@settings_bp.route('/settings')
@login_required
def index():
    """Settings index page"""
    # Get home charging rates
    home_rates = Settings.query.filter_by(
        user_id=current_user.id, 
        key='home_charging_rate'
    ).order_by(Settings.id.desc()).all()
    
    # Parse the JSON data for display
    parsed_rates = []
    for rate in home_rates:
        try:
            import json
            rate_data = json.loads(rate.value)
            rate_data['id'] = rate.id
            parsed_rates.append(rate_data)
        except (json.JSONDecodeError, KeyError):
            # Skip invalid entries
            continue
    
    # Get currency info
    currency_info = get_currency_info()
    
    # Get Phase 3 settings
    phase3_settings = get_phase3_settings()
    
    # Calculate petrol threshold
    petrol_threshold = calculate_petrol_threshold_p_per_kwh(
        float(phase3_settings['petrol_price_p_per_litre']),
        float(phase3_settings['petrol_mpg']),
        float(phase3_settings['default_efficiency_mpkwh'])
    )
    
    return render_template('settings/index.html', 
                         home_rates=parsed_rates,
                         phase3_settings=phase3_settings,
                         petrol_threshold=petrol_threshold,
                         **currency_info)

@settings_bp.route('/settings/update-currency', methods=['POST'])
@login_required
def update_currency():
    """Update user's currency preference"""
    currency = request.form.get('currency')
    
    if currency in ['GBP', 'EUR', 'USD']:
        Settings.set_setting(current_user.id, 'currency', currency)
        db.session.commit()
        flash(f'Currency updated to {currency}', 'success')
    else:
        flash('Invalid currency selected', 'error')
    
    return redirect(url_for('settings.index'))

@settings_bp.route('/settings/home-charging/new', methods=['GET', 'POST'])
@login_required
def new_home_rate():
    """Add new home charging rate"""
    form = HomeChargingRateForm()
    
    if request.method == 'POST':
        print(f"DEBUG: Form submitted. Valid: {form.validate()}")
        print(f"DEBUG: Form errors: {form.errors}")
        print(f"DEBUG: Form data: {form.data}")
    
    if form.validate_on_submit():
        print("DEBUG: Form validation passed, creating rate...")
        # Create rate data as JSON
        rate_data = {
            'rate_per_kwh': form.rate_per_kwh.data,
            'valid_from': form.valid_from.data.isoformat(),
            'valid_to': form.valid_to.data.isoformat() if form.valid_to.data else None
        }
        
        import json
        rate_json = json.dumps(rate_data)
        print(f"DEBUG: Rate JSON: {rate_json}")
        
        # Store in settings
        setting = Settings(
            user_id=current_user.id,
            key='home_charging_rate',
            value=rate_json,
            encrypted=False
        )
        
        db.session.add(setting)
        db.session.commit()
        flash('Home charging rate added successfully!', 'success')
        return redirect(url_for('settings.index'))
    
    return render_template('settings/home_rate_form.html', form=form, title='Add Home Charging Rate')

@settings_bp.route('/settings/home-charging/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_home_rate(id):
    """Edit existing home charging rate"""
    setting = Settings.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    
    try:
        import json
        rate_data = json.loads(setting.value)
        form = HomeChargingRateForm()
        
        if form.validate_on_submit():
            # Update rate data
            rate_data = {
                'rate_per_kwh': form.rate_per_kwh.data,
                'valid_from': form.valid_from.data.isoformat(),
                'valid_to': form.valid_to.data.isoformat() if form.valid_to.data else None
            }
            
            setting.value = json.dumps(rate_data)
            db.session.commit()
            flash('Home charging rate updated successfully!', 'success')
            return redirect(url_for('settings.index'))
        
        # Pre-populate form with existing data
        form.rate_per_kwh.data = rate_data.get('rate_per_kwh')
        form.valid_from.data = datetime.fromisoformat(rate_data.get('valid_from')).date()
        if rate_data.get('valid_to'):
            form.valid_to.data = datetime.fromisoformat(rate_data.get('valid_to')).date()
        
        return render_template('settings/home_rate_form.html', form=form, setting=setting, title='Edit Home Charging Rate')
        
    except (json.JSONDecodeError, KeyError, ValueError):
        flash('Invalid rate data found', 'error')
        return redirect(url_for('settings.index'))

@settings_bp.route('/settings/home-charging/<int:id>/delete', methods=['POST'])
@login_required
def delete_home_rate(id):
    """Delete home charging rate"""
    setting = Settings.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(setting)
    db.session.commit()
    flash('Home charging rate deleted successfully!', 'success')
    return redirect(url_for('settings.index'))

@settings_bp.route('/settings/home-charging/config', methods=['GET', 'POST'])
@login_required
def home_charging_config():
    """Configure home charging settings (speed and aliases)"""
    form = HomeChargingSettingsForm()
    
    if request.method == 'GET':
        # Pre-populate with current values
        current_settings = get_phase3_settings()
        form.home_charging_speed_kw.data = float(current_settings['home_charging_speed_kw'])
        form.home_aliases_csv.data = current_settings['home_aliases_csv']
    
    if form.validate_on_submit():
        # Update settings
        Settings.set_setting(current_user.id, 'home_charging_speed_kw', str(form.home_charging_speed_kw.data))
        Settings.set_setting(current_user.id, 'home_aliases_csv', form.home_aliases_csv.data)
        
        flash('Home charging configuration updated successfully!', 'success')
        return redirect(url_for('settings.index'))
    
    return render_template('settings/home_charging_config.html', form=form, title='Home Charging Configuration')

@settings_bp.route('/settings/efficiency', methods=['GET', 'POST'])
@login_required
def efficiency_settings():
    """Configure efficiency and comparison settings"""
    form = EfficiencySettingsForm()
    
    if request.method == 'GET':
        # Pre-populate with current values
        current_settings = get_phase3_settings()
        form.default_efficiency_mpkwh.data = float(current_settings['default_efficiency_mpkwh'])
    
    if form.validate_on_submit():
        # Update settings
        Settings.set_setting(current_user.id, 'default_efficiency_mpkwh', str(form.default_efficiency_mpkwh.data))
        
        flash('Efficiency settings updated successfully!', 'success')
        return redirect(url_for('settings.index'))
    
    return render_template('settings/efficiency_settings.html', form=form, title='Efficiency Settings')

@settings_bp.route('/settings/petrol-comparison', methods=['GET', 'POST'])
@login_required
def petrol_comparison():
    """Configure petrol comparison settings"""
    form = PetrolComparisonForm()
    
    if request.method == 'GET':
        # Pre-populate with current values
        current_settings = get_phase3_settings()
        form.petrol_price_p_per_litre.data = float(current_settings['petrol_price_p_per_litre'])
        form.petrol_mpg.data = float(current_settings['petrol_mpg'])
    
    if form.validate_on_submit():
        # Update settings
        Settings.set_setting(current_user.id, 'petrol_price_p_per_litre', str(form.petrol_price_p_per_litre.data))
        Settings.set_setting(current_user.id, 'petrol_mpg', str(form.petrol_mpg.data))
        
        flash('Petrol comparison settings updated successfully!', 'success')
        return redirect(url_for('settings.index'))
    
    return render_template('settings/petrol_comparison.html', form=form, title='Petrol Comparison Settings')

@settings_bp.route('/settings/notifications')
@login_required
def notifications():
    """Notification settings page"""
    # TODO: Create notifications.html template
    flash('Notifications settings not yet implemented', 'info')
    return redirect(url_for('settings.index'))

@settings_bp.route('/settings/ai-integration')
@login_required
def ai_integration():
    """AI integration settings page"""
    # TODO: Create ai_integration.html template
    flash('AI integration settings not yet implemented', 'info')
    return redirect(url_for('settings.index'))
