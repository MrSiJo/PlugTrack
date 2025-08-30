from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from models.user import db
from models.settings import Settings
from services.forms import HomeChargingRateForm, HomeChargingSettingsForm, EfficiencySettingsForm, PetrolComparisonForm, CostAnalysisForm
from services.cost_parity import petrol_ppm, ev_parity_rate_p_per_kwh, ev_parity_rate_gbp_per_kwh, format_petrol_ppm, format_ev_parity_rate
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
    
    # Phase 5.2: Get advanced settings for confidence thresholds
    from services.derived_metrics import DerivedMetricsService
    advanced_settings = {
        'min_delta_miles': Settings.get_setting(current_user.id, 'min_delta_miles', DerivedMetricsService._MIN_DELTA_MILES),
        'min_kwh': Settings.get_setting(current_user.id, 'min_kwh', DerivedMetricsService._MIN_KWH),
        'max_anchor_gap_days': Settings.get_setting(current_user.id, 'max_anchor_gap_days', DerivedMetricsService._MAX_ANCHOR_GAP_DAYS),
        'efficiency_min': Settings.get_setting(current_user.id, 'efficiency_min', DerivedMetricsService._EFF_MIN),
        'efficiency_max': Settings.get_setting(current_user.id, 'efficiency_max', DerivedMetricsService._EFF_MAX),
        'anchor_horizon_days': Settings.get_setting(current_user.id, 'anchor_horizon_days', DerivedMetricsService._ANCHOR_HORIZON_DAYS)
    }
    
    # Calculate petrol threshold using legacy function for backward compatibility
    petrol_threshold = calculate_petrol_threshold_p_per_kwh(
        float(phase3_settings['petrol_price_p_per_litre']),
        float(phase3_settings['petrol_mpg']),
        float(phase3_settings['default_efficiency_mpkwh'])
    )
    
    # Calculate formatted cost parity data using new centralized service
    petrol_ppm_value = petrol_ppm(
        float(phase3_settings['petrol_price_p_per_litre']),
        float(phase3_settings['petrol_mpg'])
    )
    ev_parity_rate_p = ev_parity_rate_p_per_kwh(
        float(phase3_settings['petrol_price_p_per_litre']),
        float(phase3_settings['petrol_mpg']),
        float(phase3_settings['default_efficiency_mpkwh'])
    )
    
    cost_parity_data = {
        'petrol_ppm_formatted': format_petrol_ppm(petrol_ppm_value),
        'ev_parity_formatted': format_ev_parity_rate(ev_parity_rate_p),
        'petrol_ppm_raw': petrol_ppm_value,
        'ev_parity_raw': ev_parity_rate_p
    }
    
    return render_template('settings/index.html', 
                         home_rates=parsed_rates,
                         phase3_settings=phase3_settings,
                         advanced_settings=advanced_settings,
                         petrol_threshold=petrol_threshold,
                         cost_parity_data=cost_parity_data,
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

@settings_bp.route('/settings/cost-analysis', methods=['GET', 'POST'])
@login_required
def cost_analysis():
    """Configure cost analysis settings (combined efficiency and petrol comparison)"""
    form = CostAnalysisForm()
    
    if request.method == 'GET':
        # Pre-populate with current values
        current_settings = get_phase3_settings()
        form.default_efficiency_mpkwh.data = float(current_settings['default_efficiency_mpkwh'])
        form.petrol_price_p_per_litre.data = float(current_settings['petrol_price_p_per_litre'])
        form.petrol_mpg.data = float(current_settings['petrol_mpg'])
    
    if form.validate_on_submit():
        # Update settings using existing keys
        Settings.set_setting(current_user.id, 'default_efficiency_mpkwh', str(form.default_efficiency_mpkwh.data))
        Settings.set_setting(current_user.id, 'petrol_price_p_per_litre', str(form.petrol_price_p_per_litre.data))
        Settings.set_setting(current_user.id, 'petrol_mpg', str(form.petrol_mpg.data))
        
        flash('Cost & efficiency settings updated successfully!', 'success')
        return redirect(url_for('settings.index'))
    
    # Calculate preview data using centralized service for display
    current_settings = get_phase3_settings()
    petrol_ppm_value = petrol_ppm(
        float(current_settings['petrol_price_p_per_litre']),
        float(current_settings['petrol_mpg'])
    )
    ev_parity_rate_p = ev_parity_rate_p_per_kwh(
        float(current_settings['petrol_price_p_per_litre']),
        float(current_settings['petrol_mpg']),
        float(current_settings['default_efficiency_mpkwh'])
    )
    
    preview_data = {
        'petrol_ppm_formatted': format_petrol_ppm(petrol_ppm_value),
        'ev_parity_formatted': format_ev_parity_rate(ev_parity_rate_p)
    }
    
    return render_template('settings/cost_analysis.html', form=form, title='Cost & Efficiency', preview_data=preview_data)

# Redirects for backward compatibility
@settings_bp.route('/settings/efficiency')
@login_required 
def efficiency_settings_redirect():
    """Redirect old efficiency settings to cost analysis"""
    return redirect(url_for('settings.cost_analysis'), code=301)

@settings_bp.route('/settings/petrol-comparison')
@login_required
def petrol_comparison_redirect():
    """Redirect old petrol comparison to cost analysis"""
    return redirect(url_for('settings.cost_analysis'), code=301)

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

@settings_bp.route('/settings/advanced', methods=['POST'])
@login_required
def advanced():
    """Save advanced settings"""
    try:
        # Get form data
        min_delta_miles = float(request.form.get('min_delta_miles', 15))
        min_kwh = float(request.form.get('min_kwh', 3.0))
        max_anchor_gap_days = int(request.form.get('max_anchor_gap_days', 10))
        efficiency_min = float(request.form.get('efficiency_min', 1.0))
        efficiency_max = float(request.form.get('efficiency_max', 7.0))
        anchor_horizon_days = int(request.form.get('anchor_horizon_days', 30))
        
        # Validate ranges
        if not (1 <= min_delta_miles <= 100):
            flash('Minimum delta miles must be between 1 and 100', 'error')
            return redirect(url_for('settings.index') + '#advanced')
            
        if not (0.1 <= min_kwh <= 50):
            flash('Minimum kWh must be between 0.1 and 50', 'error')
            return redirect(url_for('settings.index') + '#advanced')
            
        if not (1 <= max_anchor_gap_days <= 365):
            flash('Maximum anchor gap must be between 1 and 365 days', 'error')
            return redirect(url_for('settings.index') + '#advanced')
            
        if not (0.1 <= efficiency_min <= 10):
            flash('Minimum efficiency must be between 0.1 and 10 mi/kWh', 'error')
            return redirect(url_for('settings.index') + '#advanced')
            
        if not (1 <= efficiency_max <= 20):
            flash('Maximum efficiency must be between 1 and 20 mi/kWh', 'error')
            return redirect(url_for('settings.index') + '#advanced')
            
        if efficiency_min >= efficiency_max:
            flash('Minimum efficiency must be less than maximum efficiency', 'error')
            return redirect(url_for('settings.index') + '#advanced')
            
        if not (1 <= anchor_horizon_days <= 365):
            flash('Anchor horizon must be between 1 and 365 days', 'error')
            return redirect(url_for('settings.index') + '#advanced')
        
        # Save settings
        Settings.set_setting(current_user.id, 'min_delta_miles', str(min_delta_miles))
        Settings.set_setting(current_user.id, 'min_kwh', str(min_kwh))
        Settings.set_setting(current_user.id, 'max_anchor_gap_days', str(max_anchor_gap_days))
        Settings.set_setting(current_user.id, 'efficiency_min', str(efficiency_min))
        Settings.set_setting(current_user.id, 'efficiency_max', str(efficiency_max))
        Settings.set_setting(current_user.id, 'anchor_horizon_days', str(anchor_horizon_days))
        
        db.session.commit()
        flash('Advanced settings saved successfully!', 'success')
        
    except (ValueError, TypeError) as e:
        flash('Invalid input values. Please check your entries.', 'error')
        
    return redirect(url_for('settings.index') + '#advanced')
