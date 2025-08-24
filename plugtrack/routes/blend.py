from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from services.blend import BlendedChargeService
from services.derived_metrics import DerivedMetricsService
import json

blend_bp = Blueprint('blend', __name__)

@blend_bp.route('/blend/plan', methods=['POST'])
@login_required
def plan():
    """Calculate a blended charging plan"""
    try:
        data = request.get_json()
        
        # Extract parameters
        start_soc = int(data.get('start_soc', 0))
        dc_stop_soc = int(data.get('dc_stop_soc', 65))
        home_target_soc = int(data.get('home_target_soc', 80))
        dc_power_kw = float(data.get('dc_power_kw', 50.0))
        dc_cost_per_kwh = float(data.get('dc_cost_per_kwh', 0.0))
        home_cost_per_kwh = float(data.get('home_cost_per_kwh', 0.20))
        home_power_kw = float(data.get('home_power_kw', 2.3))
        car_id = int(data.get('car_id', 0))
        
        # Validate inputs
        if not (0 <= start_soc < dc_stop_soc < home_target_soc <= 100):
            return jsonify({'error': 'Invalid SoC values'}), 400
        
        if dc_power_kw <= 0 or home_power_kw <= 0:
            return jsonify({'error': 'Invalid power values'}), 400
        
        # Get car details
        car = Car.query.filter_by(id=car_id, user_id=current_user.id).first()
        if not car:
            return jsonify({'error': 'Car not found'}), 404
        
        # Calculate blended charge
        blend_result = BlendedChargeService.calculate_blended_charge(
            start_soc=start_soc,
            dc_stop_soc=dc_stop_soc,
            home_target_soc=home_target_soc,
            dc_power_kw=dc_power_kw,
            home_cost_per_kwh=home_cost_per_kwh,
            dc_cost_per_kwh=dc_cost_per_kwh,
            car_battery_kwh=car.battery_kwh,
            home_power_kw=home_power_kw
        )
        
        # Format for display
        efficiency = car.efficiency_mpkwh or float(Settings.get_setting(current_user.id, 'default_efficiency_mpkwh', '3.7'))
        formatted_result = BlendedChargeService.format_blend_summary(blend_result, efficiency)
        
        # Add additional context
        result = {
            'blend': blend_result,
            'formatted': formatted_result,
            'car': {
                'name': car.display_name,
                'battery_kwh': car.battery_kwh,
                'efficiency_mpkwh': efficiency
            },
            'rates': {
                'dc_cost_per_kwh': dc_cost_per_kwh,
                'home_cost_per_kwh': home_cost_per_kwh,
                'home_power_kw': home_power_kw
            }
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@blend_bp.route('/blend/suggest', methods=['POST'])
@login_required
def suggest():
    """Get suggested DC stop point based on cost comparison"""
    try:
        data = request.get_json()
        start_soc = int(data.get('start_soc', 0))
        dc_cost_per_kwh = float(data.get('dc_cost_per_kwh', 0.0))
        car_id = int(data.get('car_id', 0))
        
        # Get car details
        car = Car.query.filter_by(id=car_id, user_id=current_user.id).first()
        if not car:
            return jsonify({'error': 'Car not found'}), 404
        
        # Get home rate from settings
        home_rate_p_per_kwh = float(Settings.get_setting(current_user.id, 'home_rate_p_per_kwh', '20.0'))
        home_cost_per_kwh = home_rate_p_per_kwh / 100
        
        # Calculate optimal DC stop
        optimal_stop = BlendedChargeService.get_optimal_dc_stop(
            start_soc, home_cost_per_kwh, dc_cost_per_kwh
        )
        
        return jsonify({
            'suggested_dc_stop': optimal_stop,
            'home_rate': home_cost_per_kwh,
            'dc_rate': dc_cost_per_kwh
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@blend_bp.route('/blend/save', methods=['POST'])
@login_required
def save_plan():
    """Save a blend plan to session notes"""
    try:
        data = request.get_json()
        session_id = int(data.get('session_id', 0))
        blend_plan = data.get('blend_plan', {})
        
        # Get session
        session = ChargingSession.query.filter_by(id=session_id, user_id=current_user.id).first()
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        
        # Format plan for notes
        plan_text = f"""
Blended Charge Plan:
- DC: {blend_plan.get('dc', {}).get('soc_range', 'N/A')} - {blend_plan.get('dc', {}).get('kwh', 0):.1f} kWh
- Home: {blend_plan.get('home', {}).get('soc_range', 'N/A')} - {blend_plan.get('home', {}).get('kwh', 0):.1f} kWh
- Total: £{blend_plan.get('total', {}).get('cost', 0):.2f}
        """.strip()
        
        # Append to existing notes
        if session.notes:
            session.notes += f"\n\n{plan_text}"
        else:
            session.notes = plan_text
        
        from models.user import db
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Plan saved to session notes'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
