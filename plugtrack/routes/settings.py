from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from models.user import db
from models.settings import Settings
from services.forms import HomeChargingRateForm
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
    
    return render_template('settings/index.html', 
                         home_rates=parsed_rates,
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
    else:
        print("DEBUG: Form validation failed")
    
    return render_template('settings/home_rate_form.html', form=form)

@settings_bp.route('/settings/home-charging/<int:id>/delete', methods=['POST'])
@login_required
def delete_home_rate(id):
    """Delete home charging rate"""
    setting = Settings.query.filter_by(id=id, user_id=current_user.id, key='home_charging_rate').first_or_404()
    db.session.delete(setting)
    db.session.commit()
    flash('Home charging rate deleted successfully!', 'success')
    return redirect(url_for('settings.index'))

@settings_bp.route('/settings/notifications')
@login_required
def notifications():
    """Notification settings page"""
    return render_template('settings/notifications.html')

@settings_bp.route('/settings/ai-integration')
@login_required
def ai_integration():
    """AI integration settings page"""
    return render_template('settings/ai_integration.html')
