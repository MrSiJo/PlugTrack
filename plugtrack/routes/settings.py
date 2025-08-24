from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from ..models.settings import Settings, db
from ..services.forms import HomeChargingRateForm
from ..services.encryption import EncryptionService
from datetime import datetime, date

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings')
@login_required
def index():
    # Get home charging rates
    home_rates = Settings.query.filter_by(
        user_id=current_user.id, 
        key='home_charging_rate'
    ).order_by(Settings.id.desc()).all()
    
    # Get notification settings
    gotify_url = Settings.get_setting(current_user.id, 'gotify_url', '')
    gotify_token = Settings.get_setting(current_user.id, 'gotify_token', '')
    
    # Get AI integration settings
    openai_api_key = Settings.get_setting(current_user.id, 'openai_api_key', '')
    anthropic_api_key = Settings.get_setting(current_user.id, 'anthropic_api_key', '')
    
    return render_template('settings/index.html',
                         home_rates=home_rates,
                         gotify_url=gotify_url,
                         gotify_token=gotify_token,
                         openai_api_key=openai_api_key,
                         anthropic_api_key=anthropic_api_key)

@settings_bp.route('/settings/home-charging/new', methods=['GET', 'POST'])
@login_required
def new_home_rate():
    form = HomeChargingRateForm()
    
    if form.validate_on_submit():
        # Store as JSON-like string for simplicity
        rate_data = {
            'rate_per_kwh': form.rate_per_kwh.data,
            'valid_from': form.valid_from.data.isoformat(),
            'valid_to': form.valid_to.data.isoformat() if form.valid_to.data else None
        }
        
        import json
        rate_json = json.dumps(rate_data)
        
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

@settings_bp.route('/settings/home-charging/<int:id>/delete', methods=['POST'])
@login_required
def delete_home_rate(id):
    setting = Settings.query.filter_by(id=id, user_id=current_user.id, key='home_charging_rate').first_or_404()
    db.session.delete(setting)
    db.session.commit()
    flash('Home charging rate deleted successfully!', 'success')
    return redirect(url_for('settings.index'))

@settings_bp.route('/settings/notifications', methods=['POST'])
@login_required
def update_notifications():
    gotify_url = request.form.get('gotify_url', '').strip()
    gotify_token = request.form.get('gotify_token', '').strip()
    
    # Update settings
    Settings.set_setting(current_user.id, 'gotify_url', gotify_url)
    Settings.set_setting(current_user.id, 'gotify_token', gotify_token, encrypted=True)
    
    flash('Notification settings updated successfully!', 'success')
    return redirect(url_for('settings.index'))

@settings_bp.route('/settings/ai-integration', methods=['POST'])
@login_required
def update_ai_integration():
    openai_api_key = request.form.get('openai_api_key', '').strip()
    anthropic_api_key = request.form.get('anthropic_api_key', '').strip()
    
    # Update settings
    Settings.set_setting(current_user.id, 'openai_api_key', openai_api_key, encrypted=True)
    Settings.set_setting(current_user.id, 'anthropic_api_key', anthropic_api_key, encrypted=True)
    
    flash('AI integration settings updated successfully!', 'success')
    return redirect(url_for('settings.index'))
