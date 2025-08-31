from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from models.session_meta import SessionMeta
from sqlalchemy import func, and_, or_, not_, case
from datetime import datetime, timedelta
import pandas as pd

class DerivedMetricsService:
    """Service for calculating derived metrics from charging session data"""

    # tuning knobs
    _ANCHOR_HORIZON_DAYS = 30
    _EFF_MIN = 1.0
    _EFF_MAX = 7.0
    _DEBUG_EFF = True  # flip to True temporarily if you want console logs
    
    # confidence thresholds
    _MIN_DELTA_MILES = 15
    _MIN_KWH = 3.0
    _MAX_ANCHOR_GAP_DAYS = 10

    # -------- helpers --------
    @staticmethod
    def _is_home_like(session):
        """True if session is home charging. Prefers explicit flag, falls back to label match."""
        try:
            if hasattr(session, "is_home_charging") and session.is_home_charging is not None:
                return bool(session.is_home_charging)
        except Exception:
            pass
        label = (session.location_label or "").lower()
        return any(a in label for a in ("home", "garage", "driveway"))

    @staticmethod
    def classify_session_size(delta_soc: float) -> str:
        """Classify session size based on SoC delta"""
        if delta_soc <= 20:
            return "topup"
        elif delta_soc <= 50:
            return "partial"
        else:
            return "major"

    @staticmethod
    def is_low_confidence(delta_miles: float, kwh: float) -> bool:
        """Determine if session has low confidence due to small window"""
        # If either value is None, we can't have high confidence
        if delta_miles is None or kwh is None:
            return True
        return delta_miles <= DerivedMetricsService._MIN_DELTA_MILES or kwh <= DerivedMetricsService._MIN_KWH

    @staticmethod
    def get_confidence_info(delta_miles: float, kwh: float, anchor_gap_days: int = None, efficiency: float = None) -> dict:
        """
        Get structured confidence information with reasons.
        Returns: {level: 'high'|'medium'|'low', reasons: [list of reason strings]}
        """
        reasons = []
        
        # Check for small window reasons
        if delta_miles is not None and delta_miles <= DerivedMetricsService._MIN_DELTA_MILES:
            reasons.append(f"small_window (Δ{delta_miles:.1f} mi ≤ {DerivedMetricsService._MIN_DELTA_MILES})")
        
        if kwh is not None and kwh <= DerivedMetricsService._MIN_KWH:
            reasons.append(f"small_window ({kwh:.1f} kWh ≤ {DerivedMetricsService._MIN_KWH})")
        
        # Check for stale anchors
        if anchor_gap_days is not None and anchor_gap_days > DerivedMetricsService._MAX_ANCHOR_GAP_DAYS:
            reasons.append(f"stale_anchors ({anchor_gap_days} days > {DerivedMetricsService._MAX_ANCHOR_GAP_DAYS})")
        
        # Check for outlier clamping
        if efficiency is not None:
            if efficiency <= DerivedMetricsService._EFF_MIN:
                reasons.append(f"outlier_clamped ({efficiency:.1f} mi/kWh ≤ {DerivedMetricsService._EFF_MIN})")
            elif efficiency >= DerivedMetricsService._EFF_MAX:
                reasons.append(f"outlier_clamped ({efficiency:.1f} mi/kWh ≥ {DerivedMetricsService._EFF_MAX})")
        
        # Determine confidence level
        if not reasons:
            level = 'high'
        elif len(reasons) == 1:
            level = 'medium'
        else:
            level = 'low'
        
        return {
            'level': level,
            'reasons': reasons
        }

    @staticmethod
    def _compute_session_observed_efficiency(session):
        """
        Observed mi/kWh for THIS session:
        - miles = odometer_now - odometer_at_previous_anchor (same user/car) within horizon
        - kWh   = sum of charge_delivered_kwh where prev < (date,id) <= current (same user/car)
        Returns dict with efficiency and anchor gap info, or None if not enough data.
        """
        if session.odometer is None:
            return None

        # Skip baseline sessions - they don't contribute to efficiency calculations
        if hasattr(session, 'is_baseline') and session.is_baseline:
            if DerivedMetricsService._DEBUG_EFF:
                print(f"Session {session.id} ({session.date}): Skipping baseline session")
            return None

        # previous anchor (strictly before this session: date then id) within horizon
        start = session.date - timedelta(days=DerivedMetricsService._ANCHOR_HORIZON_DAYS)
        prev = (ChargingSession.query
                .filter(
                    ChargingSession.user_id == session.user_id,
                    ChargingSession.car_id == session.car_id,
                    ChargingSession.odometer.isnot(None),
                    ChargingSession.is_baseline == False,  # Exclude baseline sessions
                    ChargingSession.date >= start,
                    (ChargingSession.date < session.date) |
                    and_(ChargingSession.date == session.date,
                         ChargingSession.id < session.id)
                )
                .order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
                .first())

        if not prev or prev.odometer is None:
            if DerivedMetricsService._DEBUG_EFF:
                print(f"Session {session.id} ({session.date}): No previous anchor found")
            return None

        miles = float(session.odometer - prev.odometer)
        if miles <= 0:
            if DerivedMetricsService._DEBUG_EFF:
                print(f"Session {session.id} ({session.date}): Invalid miles delta: {miles}")
            return None

        # Simplified kWh calculation: just use the current session's kWh
        # This is more accurate for per-session efficiency anyway
        window_kwh = float(session.charge_delivered_kwh or 0)
        
        if window_kwh <= 0:
            if DerivedMetricsService._DEBUG_EFF:
                print(f"Session {session.id} ({session.date}): No kWh delivered: {window_kwh}")
            return None

        eff = miles / window_kwh
        # clamp outliers (missed logs / data entry mistakes)
        if eff < DerivedMetricsService._EFF_MIN or eff > DerivedMetricsService._EFF_MAX:
            if DerivedMetricsService._DEBUG_EFF:
                print(f"Session {session.id} ({session.date}): Efficiency {eff} outside valid range [{DerivedMetricsService._EFF_MIN}, {DerivedMetricsService._EFF_MAX}]")
            return None
        
        # Calculate anchor gap in days
        anchor_gap_days = (session.date - prev.date).days
            
        if DerivedMetricsService._DEBUG_EFF:
            print({
                'session_id': session.id,
                'session_date': str(session.date),
                'anchor_id': prev.id,
                'anchor_date': str(prev.date),
                'miles': miles,
                'kwh_window': float(window_kwh),
                'eff_observed': round(eff, 2),
                'anchor_gap_days': anchor_gap_days
            })
        
        return {
            'efficiency': round(eff, 2),
            'anchor_gap_days': anchor_gap_days
        }
    
    @staticmethod
    def get_miles_since_previous_session(session):
        """
        Get miles driven since the previous charging session.
        Returns dict with miles, previous session info, or None if no previous session found.
        """
        if session.odometer is None:
            return None

        # Find the most recent previous session (same user/car) with odometer data
        prev = (ChargingSession.query
                .filter(
                    ChargingSession.user_id == session.user_id,
                    ChargingSession.car_id == session.car_id,
                    ChargingSession.odometer.isnot(None),
                    (ChargingSession.date < session.date) |
                    and_(ChargingSession.date == session.date,
                         ChargingSession.id < session.id)
                )
                .order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
                .first())

        if not prev or prev.odometer is None:
            return None

        miles = float(session.odometer - prev.odometer)
        if miles < 0:
            return None  # Invalid odometer readings

        # Calculate days between sessions
        days_between = (session.date - prev.date).days
        
        return {
            'miles': miles,
            'days': days_between,
            'previous_session': {
                'id': prev.id,
                'date': prev.date,
                'location': prev.location_label,
                'odometer': prev.odometer
            }
        }

    @staticmethod
    def _resolve_efficiency(user_id, car):
        """Return (efficiency_mpkwh_or_none, source, warning_or_none).
        Priority:
        1) Dynamic recent efficiency from session data (scoped: AC + home-only)
        1b) Dynamic recent efficiency from session data (AC only)
        2) Car.efficiency_mpkwh
        3) User default from Settings (if configured)
        4) Missing
        """
        # 1) Dynamic (observed odometer-based) – AC + Home-only first
        if car:
            dynamic_eff = DerivedMetricsService.calculate_dynamic_efficiency(
                user_id, car_id=car.id, charge_type_filter='AC', home_only=True
            )
            if dynamic_eff and dynamic_eff > 0:
                return float(dynamic_eff), 'dynamic_recent_home_ac', None
            # 1b) AC only
            dynamic_eff = DerivedMetricsService.calculate_dynamic_efficiency(
                user_id, car_id=car.id, charge_type_filter='AC', home_only=False
            )
            if dynamic_eff and dynamic_eff > 0:
                return float(dynamic_eff), 'dynamic_recent_ac', None
        # 2) Car value
        if car and car.efficiency_mpkwh:
            return float(car.efficiency_mpkwh), 'car', None
        # 3) User setting (configured in Settings UI)
        setting_val = Settings.get_setting(user_id, 'default_efficiency_mpkwh', None)
        if setting_val is not None and str(setting_val).strip() != '':
            try:
                return float(setting_val), 'user_setting', None
            except Exception:
                pass
        # 4) Missing
        return None, 'missing', (
            'EV efficiency (mi/kWh) is not available. Set it per-car or provide a default in Settings ➜ Efficiency.'
        )

    @staticmethod
    def calculate_session_metrics(session, car):
        """Calculate metrics for a single charging session"""
        warnings = []
        # ------------------------------------------------------------------
        # Efficiency resolution – prefer observed per-session (no fallback)
        # ------------------------------------------------------------------
        efficiency = None
        efficiency_source = 'missing'

        observed = DerivedMetricsService._compute_session_observed_efficiency(session)
        if observed is not None:
            efficiency = observed['efficiency']
            efficiency_source = 'observed_session'
            anchor_gap_days = observed['anchor_gap_days']
        else:
            anchor_gap_days = None
            # Optional fallback, controlled by setting
            allow_fb = Settings.get_setting(session.user_id, 'allow_efficiency_fallback', '0')
            if str(allow_fb).strip() == '1':
                eff_fb, eff_src, warn = DerivedMetricsService._resolve_efficiency(session.user_id, car)
                if eff_fb:
                    efficiency = eff_fb
                    efficiency_source = eff_src
                if warn:
                    warnings.append(warn)
        
        # Total cost
        total_cost = session.charge_delivered_kwh * session.cost_per_kwh
        
        # Miles gained (based on efficiency if available)
        miles_gained = (session.charge_delivered_kwh * efficiency) if efficiency else 0
        
        # Cost per mile
        cost_per_mile = (total_cost / miles_gained) if miles_gained > 0 else 0
        
        # Battery added percentage
        battery_added_percent = session.soc_to - session.soc_from
        
        # Percentage per kWh (indicates effective usable capacity vs losses)
        percent_per_kwh = (battery_added_percent / session.charge_delivered_kwh) if session.charge_delivered_kwh > 0 else 0
        
        # Average power (when duration present)
        avg_power_kw = (session.charge_delivered_kwh / (session.duration_mins / 60)) if session.duration_mins and session.duration_mins > 0 else 0
        
        # DC taper flag (heuristic)
        dc_taper_flag = (session.charge_type == 'DC' and session.soc_to > 65)
        
        # Petrol threshold comparison
        try:
            if efficiency:
                from utils.petrol_calculations import get_petrol_threshold_for_user
                petrol_threshold = get_petrol_threshold_for_user(session.user_id, efficiency)
                threshold_ppm = petrol_threshold / efficiency if efficiency > 0 else 0
            else:
                petrol_threshold = 0
                threshold_ppm = 0
        except Exception:
            petrol_threshold = 0
            threshold_ppm = 0
        is_cheaper_than_petrol = (cost_per_mile * 100) <= threshold_ppm if (cost_per_mile > 0 and threshold_ppm > 0) else False
        
        # Home vs public charging
        is_home_charging = session.is_home_charging
        
        # Calculate delta miles for confidence detection
        delta_miles = None
        if observed is not None:
            # Calculate delta miles from efficiency and kWh
            if efficiency and session.charge_delivered_kwh:
                delta_miles = efficiency * session.charge_delivered_kwh
        
        # Session size classification
        delta_soc = max(0.0, float(session.soc_to - session.soc_from))
        size_bucket = DerivedMetricsService.classify_session_size(delta_soc)
        
        # Get structured confidence information
        confidence_info = DerivedMetricsService.get_confidence_info(
            delta_miles=delta_miles,
            kwh=session.charge_delivered_kwh,
            anchor_gap_days=anchor_gap_days,
            efficiency=efficiency
        )
        
        # Legacy confidence flag for backward compatibility
        low_confidence = confidence_info['level'] == 'low'
        
        # Use confidence level from structured info
        efficiency_confidence = confidence_info['level']
        
        # Calculate mphC (miles per charging hour)
        mphc = 0
        if session.duration_mins and session.duration_mins > 0 and miles_gained > 0:
            hours = session.duration_mins / 60.0
            mphc = miles_gained / hours
        
        # Phase 5.1 Insights - Calculate new metrics using insights service
        from services.insights import InsightsService
        
        # £/10% SOC metric
        cost_per_10_percent = InsightsService.calculate_cost_per_10_percent_soc(session, total_cost)
        
        # Home ROI delta (calculated when needed, stored as None for now)
        home_roi_delta = None  # Will be calculated in UI when displaying
        
        # Loss estimate
        loss_estimate = InsightsService.calculate_loss_estimate(session, car)
        
        return {
            'total_cost': total_cost,
            'miles_gained': miles_gained,
            'cost_per_mile': cost_per_mile,
            'battery_added_percent': battery_added_percent,
            'percent_per_kwh': percent_per_kwh,
            'avg_power_kw': avg_power_kw,
            'dc_taper_flag': dc_taper_flag,
            'threshold_ppm': threshold_ppm,
            'is_cheaper_than_petrol': is_cheaper_than_petrol,
            'efficiency_used': efficiency if efficiency else None,
            'efficiency_source': efficiency_source,
            'efficiency_confidence': efficiency_confidence,
            'confidence_reasons': confidence_info['reasons'],
            'delta_miles': delta_miles,
            'size_bucket': size_bucket,
            'low_confidence': low_confidence,
            'mphc': mphc,
            'warnings': warnings,
            # Phase 5.1 new metrics
            'cost_per_10_percent': cost_per_10_percent,
            'home_roi_delta': home_roi_delta,
            'loss_estimate': loss_estimate
        }

    @staticmethod
    def get_dashboard_metrics(user_id, date_from=None, date_to=None, car_id=None):
        """Get comprehensive dashboard metrics"""
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        
        # Apply filters
        if date_from:
            query = query.filter(ChargingSession.date >= date_from)
        if date_to:
            query = query.filter(ChargingSession.date <= date_to)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get basic counts and sums
        total_sessions = query.count()
        
        if total_sessions == 0:
            return {
                'total_sessions': 0,
                'total_kwh': 0,
                'total_cost': 0,
                'total_miles': 0,
                'avg_cost_per_kwh': 0,
                'avg_cost_per_mile': 0,
                'weighted_efficiency': 0,
                'free_sessions': 0,
                'paid_sessions': 0,
                'home_public_split': {'home': {'count': 0, 'percentage': 0}, 'public': {'count': 0, 'percentage': 0}},
                'ac_dc_split': {'AC': {'count': 0, 'percentage': 0}, 'DC': {'count': 0, 'percentage': 0}}
            }
        
        # Get energy and cost totals
        energy_cost = query.with_entities(
            func.sum(ChargingSession.charge_delivered_kwh).label('total_kwh'),
            func.sum(ChargingSession.charge_delivered_kwh * ChargingSession.cost_per_kwh).label('total_cost')
        ).first()
        
        total_kwh = energy_cost.total_kwh or 0
        total_cost = energy_cost.total_cost or 0
        
        # Calculate averages - handle free charging sessions properly
        # Get paid sessions only for average cost calculation
        paid_sessions_query = query.filter(ChargingSession.cost_per_kwh > 0)
        paid_kwh = paid_sessions_query.with_entities(
            func.sum(ChargingSession.charge_delivered_kwh)
        ).scalar() or 0
        
        avg_cost_per_kwh = total_cost / paid_kwh if paid_kwh > 0 else 0
        
        # Count free vs paid sessions
        free_sessions = query.filter(ChargingSession.cost_per_kwh == 0).count()
        paid_sessions = total_sessions - free_sessions
        
        # Get home vs public split
        home_sessions = query.filter(
            or_(
                ChargingSession.location_label.ilike('%home%'),
                ChargingSession.location_label.ilike('%garage%'),
                ChargingSession.location_label.ilike('%driveway%')
            )
        ).count()
        
        public_sessions = total_sessions - home_sessions
        
        # Calculate percentages for home vs public
        home_percentage = (home_sessions / total_sessions * 100) if total_sessions > 0 else 0
        public_percentage = (public_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        # Get AC vs DC split
        ac_sessions = query.filter_by(charge_type='AC').count()
        dc_sessions = query.filter_by(charge_type='DC').count()
        
        # Calculate percentages for AC vs DC
        ac_percentage = (ac_sessions / total_sessions * 100) if total_sessions > 0 else 0
        dc_percentage = (dc_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        # Calculate kWh-weighted efficiency and total miles
        total_miles = 0
        avg_cost_per_mile = 0
        weighted_efficiency = 0
        
        # Get sessions with observed efficiency for weighted calculations
        sessions_with_eff = query.filter(
            ChargingSession.odometer.isnot(None),
            ChargingSession.is_baseline == False
        ).all()
        
        if sessions_with_eff:
            # Calculate kWh-weighted efficiency
            total_weighted_numerator = 0
            total_weighted_denominator = 0
            
            for sess in sessions_with_eff:
                metrics = DerivedMetricsService.calculate_session_metrics(sess, None)
                if metrics['efficiency_used'] and not metrics['low_confidence']:
                    total_weighted_numerator += metrics['efficiency_used'] * sess.charge_delivered_kwh
                    total_weighted_denominator += sess.charge_delivered_kwh
            
            if total_weighted_denominator > 0:
                weighted_efficiency = total_weighted_numerator / total_weighted_denominator
                total_miles = total_kwh * weighted_efficiency
                avg_cost_per_mile = total_cost / total_miles if total_miles > 0 else 0
            else:
                # Fallback to car efficiency if no observed data
                if not car_id:
                    available_car = Car.query.filter_by(user_id=user_id).first()
                    dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id)
                    car_efficiency = available_car.efficiency_mpkwh if available_car else None
                    final_efficiency = dynamic_efficiency or car_efficiency
                else:
                    car = Car.query.get(car_id)
                    dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id, car_id)
                    car_efficiency = car.efficiency_mpkwh if car else None
                    final_efficiency = dynamic_efficiency or car_efficiency
                
                if final_efficiency:
                    total_miles = total_kwh * final_efficiency
                    avg_cost_per_mile = total_cost / total_miles if total_miles > 0 else 0
        
        return {
            'total_sessions': total_sessions,
            'total_kwh': total_kwh,
            'total_cost': total_cost,
            'total_miles': total_miles,
            'avg_cost_per_kwh': avg_cost_per_kwh,
            'avg_cost_per_mile': avg_cost_per_mile,
            'weighted_efficiency': weighted_efficiency,
            'free_sessions': free_sessions,
            'paid_sessions': paid_sessions,
            'home_public_split': {
                'home': {'count': home_sessions, 'percentage': home_percentage},
                'public': {'count': public_sessions, 'percentage': public_percentage}
            },
            'ac_dc_split': {
                'AC': {'count': ac_sessions, 'percentage': ac_percentage},
                'DC': {'count': dc_sessions, 'percentage': dc_percentage}
            }
        }

    @staticmethod
    def get_chart_data(user_id, date_from=None, date_to=None, car_id=None):
        """Get data formatted for charts"""
        # Build base query
        query = ChargingSession.query.filter_by(user_id=user_id)
        
        # Apply filters
        if date_from:
            query = query.filter(ChargingSession.date >= date_from)
        if date_to:
            query = query.filter(ChargingSession.date <= date_to)
        if car_id:
            query = query.filter_by(car_id=car_id)
        
        # Get daily aggregated data
        daily_data = query.with_entities(
            ChargingSession.date,
            func.sum(ChargingSession.charge_delivered_kwh).label('total_kwh'),
            func.avg(ChargingSession.charge_delivered_kwh / ChargingSession.duration_mins * 60).label('avg_power_kw')
        ).group_by(ChargingSession.date).order_by(ChargingSession.date).all()
        
        # Get daily cost data (only from paid sessions)
        daily_cost_data = query.filter(ChargingSession.cost_per_kwh > 0).with_entities(
            ChargingSession.date,
            func.avg(ChargingSession.cost_per_kwh).label('avg_cost_per_kwh'),
            func.sum(ChargingSession.charge_delivered_kwh * ChargingSession.cost_per_kwh).label('daily_cost')
        ).group_by(ChargingSession.date).order_by(ChargingSession.date).all()
        
        # Create a lookup for daily costs
        cost_lookup = {str(d.date): {'avg_cost': d.avg_cost_per_kwh, 'daily_cost': d.daily_cost} for d in daily_cost_data}
        
        # Get AC/DC split data
        ac_dc_data = query.with_entities(
            ChargingSession.date,
            func.sum(
                case(
                    (ChargingSession.charge_type == 'AC', ChargingSession.charge_delivered_kwh),
                    else_=0
                )
            ).label('ac_kwh'),
            func.sum(
                case(
                    (ChargingSession.charge_type == 'DC', ChargingSession.charge_delivered_kwh),
                    else_=0
                )
            ).label('dc_kwh')
        ).group_by(ChargingSession.date).order_by(ChargingSession.date).all()
        
        # Format for Chart.js
        dates = [str(d.date) for d in daily_data]
        cost_per_kwh = []
        energy_delivered = [float(d.total_kwh) for d in daily_data]
        
        # Handle cost per kWh - use 0 for days with only free charging
        for d in daily_data:
            date_str = str(d.date)
            if date_str in cost_lookup:
                cost_per_kwh.append(float(cost_lookup[date_str]['avg_cost']))
            else:
                cost_per_kwh.append(0.0)
        
        # Calculate kWh-weighted efficiency (mi/kWh) for each day based on session data
        efficiency = []
        for d in daily_data:
            if d.total_kwh > 0:
                # Get sessions for this day to calculate weighted efficiency
                daily_sessions = query.filter(
                    ChargingSession.date == d.date,
                    ChargingSession.odometer.isnot(None),
                    ChargingSession.is_baseline == False
                ).all()
                
                if daily_sessions:
                    # Calculate kWh-weighted efficiency for this day
                    daily_weighted_numerator = 0
                    daily_weighted_denominator = 0
                    
                    for sess in daily_sessions:
                        metrics = DerivedMetricsService.calculate_session_metrics(sess, None)
                        if metrics['efficiency_used'] and not metrics['low_confidence']:
                            daily_weighted_numerator += metrics['efficiency_used'] * sess.charge_delivered_kwh
                            daily_weighted_denominator += sess.charge_delivered_kwh
                    
                    if daily_weighted_denominator > 0:
                        daily_efficiency = daily_weighted_numerator / daily_weighted_denominator
                    else:
                        # Fallback to simple average if no observed data
                        daily_efficiency = DerivedMetricsService._calculate_daily_efficiency(user_id, d.date, car_id)
                else:
                    daily_efficiency = 0
                
                efficiency.append(daily_efficiency)
            else:
                efficiency.append(0)
        
        # AC/DC split data
        ac_energy = [float(d.ac_kwh or 0) for d in ac_dc_data]
        dc_energy = [float(d.dc_kwh or 0) for d in ac_dc_data]
        
        # Calculate cost per mile for each day using weighted efficiency
        cost_per_mile = []
        for i, d in enumerate(daily_data):
            date_str = str(d.date)
            if d.total_kwh > 0 and efficiency[i] > 0:
                miles = d.total_kwh * efficiency[i]
                if date_str in cost_lookup:
                    daily_cost = cost_lookup[date_str]['daily_cost']
                    cost_per_mile.append(daily_cost / miles if miles > 0 else 0)
                else:
                    # Free charging day
                    cost_per_mile.append(0)
            else:
                cost_per_mile.append(0)
        
        return {
            'dates': dates,
            'cost_per_kwh': cost_per_kwh,
            'cost_per_mile': cost_per_mile,
            'energy_delivered': energy_delivered,
            'ac_energy': ac_energy,
            'dc_energy': dc_energy,
            'efficiency': efficiency
        }

    @staticmethod
    def get_recommendations(user_id, active_car):
        """Get rule-based recommendations"""
        recommendations = []
        
        if not active_car:
            return recommendations
        
        # Check if 100% charge is overdue
        if active_car.recommended_full_charge_enabled:
            last_full_charge = ChargingSession.query.filter_by(
                user_id=user_id,
                car_id=active_car.id
            ).filter(ChargingSession.soc_to >= 95).order_by(ChargingSession.date.desc()).first()
            
            if last_full_charge:
                days_since_full = (datetime.now().date() - last_full_charge.date).days
                frequency_days = active_car.recommended_full_charge_frequency_value
                
                if active_car.recommended_full_charge_frequency_unit == 'months':
                    frequency_days = frequency_days * 30
                
                if days_since_full > frequency_days:
                    recommendations.append({
                        'type': 'warning',
                        'title': '100% Charge Overdue',
                        'message': f'100% charge overdue by {days_since_full - frequency_days} days',
                        'icon': 'bi-exclamation-triangle'
                    })
        
        # Check home vs public charging costs
        home_sessions = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == active_car.id,
                or_(
                    ChargingSession.location_label.ilike('%home%'),
                    ChargingSession.location_label.ilike('%garage%')
                )
            )
        ).all()
        
        public_sessions = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == active_car.id,
                not_(
                    or_(
                        ChargingSession.location_label.ilike('%home%'),
                        ChargingSession.location_label.ilike('%garage%')
                    )
                )
            )
        ).all()
        
        if home_sessions and public_sessions:
            avg_home_cost = sum(s.cost_per_kwh for s in home_sessions) / len(home_sessions)
            avg_public_cost = sum(s.cost_per_kwh for s in public_sessions) / len(public_sessions)
            
            if avg_home_cost < avg_public_cost:
                recommendations.append({
                    'type': 'info',
                    'title': 'Home Charging Advantage',
                    'message': f'Home charging is cheaper (£{avg_home_cost:.4f}/kWh vs £{avg_public_cost:.4f}/kWh average for public charging)',
                    'icon': 'bi-house'
                })
            else:
                recommendations.append({
                    'type': 'info',
                    'title': 'Public Charging Advantage',
                    'message': f'Public charging is cheaper (£{avg_public_cost:.4f}/kWh vs £{avg_home_cost:.4f}/kWh average for home charging)',
                    'icon': 'bi-lightning'
                })
        
        # Add general insights based on charging patterns
        total_sessions = ChargingSession.query.filter_by(user_id=user_id, car_id=active_car.id).count()
        
        if total_sessions >= 3:  # Only show after some data is collected
            # Check for free charging opportunities
            free_sessions = ChargingSession.query.filter(
                and_(
                    ChargingSession.user_id == user_id,
                    ChargingSession.car_id == active_car.id,
                    ChargingSession.cost_per_kwh == 0
                )
            ).count()
            
            if free_sessions > 0:
                recommendations.append({
                    'type': 'success',
                    'title': 'Free Charging Utilized',
                    'message': f'Great job! You\'ve had {free_sessions} free charging session(s). Keep an eye out for workplace, dealer, or public free charging opportunities.',
                    'icon': 'bi-gift'
                })
            
            # Check charging efficiency
            recent_sessions = ChargingSession.query.filter_by(
                user_id=user_id, 
                car_id=active_car.id
            ).order_by(ChargingSession.date.desc()).limit(5).all()
            
            if recent_sessions:
                avg_duration = sum(s.duration_mins for s in recent_sessions) / len(recent_sessions)
                avg_kwh = sum(s.charge_delivered_kwh for s in recent_sessions) / len(recent_sessions)
                
                if avg_kwh > 0:
                    avg_power = (avg_kwh / (avg_duration / 60))
                    
                    if avg_power < 3.0:  # Low power charging
                        recommendations.append({
                            'type': 'info',
                            'title': 'Slow Charging Detected',
                            'message': f'Your recent sessions average {avg_power:.1f} kW. Consider faster chargers for longer trips, or use slow charging for battery health.',
                            'icon': 'bi-speedometer'
                        })
                    elif avg_power > 20.0:  # High power charging
                        recommendations.append({
                            'type': 'info',
                            'title': 'Fast Charging Used',
                            'message': f'You\'re using fast chargers ({avg_power:.1f} kW average). Remember that frequent fast charging can impact battery longevity.',
                            'icon': 'bi-lightning-charge'
                        })
        
        # If no specific recommendations, provide general tips
        if not recommendations:
            recommendations.append({
                'type': 'info',
                'title': 'Getting Started',
                'message': 'Add more charging sessions to get personalized recommendations. Track your costs, locations, and charging patterns for better insights.',
                'icon': 'bi-info-circle'
            })
        
        return recommendations

    @staticmethod
    def get_current_efficiency_info(user_id, car_id=None):
        """Get current efficiency information for display"""
        dynamic_efficiency = DerivedMetricsService.calculate_dynamic_efficiency(user_id, car_id)
        
        if car_id:
            car = Car.query.get(car_id)
            car_efficiency = car.efficiency_mpkwh if car else None
        else:
            available_car = Car.query.filter_by(user_id=user_id).first()
            car_efficiency = available_car.efficiency_mpkwh if available_car else None
        
        return {
            'dynamic_efficiency': dynamic_efficiency,
            'car_profile_efficiency': car_efficiency,
            'final_efficiency': dynamic_efficiency or car_efficiency,
            'source': 'dynamic' if dynamic_efficiency else 'car_profile' if car_efficiency else 'none'
        }

    @staticmethod
    def get_similar_sessions(session, limit=5):
        """Find similar sessions for comparison and delta calculations"""
        # Get sessions with same car and either:
        # 1. Same charge type and overlapping SoC window (±10% of soc_from), OR
        # 2. Same location/network
        
        # Build base query for same car
        base_query = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == session.user_id,
                ChargingSession.car_id == session.car_id,
                ChargingSession.id != session.id  # Exclude current session
            )
        )
        
        # Get sessions with same charge type and overlapping SoC window
        soc_window_query = base_query.filter(
            and_(
                ChargingSession.charge_type == session.charge_type,
                ChargingSession.soc_from >= max(0, session.soc_from - 10),
                ChargingSession.soc_from <= min(100, session.soc_from + 10)
            )
        ).order_by(ChargingSession.date.desc()).limit(limit)
        
        # Get sessions with same location/network
        location_query = base_query.filter(
            or_(
                ChargingSession.location_label.ilike(f'%{session.location_label}%'),
                ChargingSession.charge_network == session.charge_network
            )
        ).order_by(ChargingSession.date.desc()).limit(limit)
        
        # Combine and deduplicate results
        similar_sessions = []
        seen_ids = set()
        
        for s in soc_window_query.all():
            if s.id not in seen_ids:
                similar_sessions.append(s)
                seen_ids.add(s.id)
        
        for s in location_query.all():
            if s.id not in seen_ids and len(similar_sessions) < limit:
                similar_sessions.append(s)
                seen_ids.add(s.id)
        
        return similar_sessions[:limit]

    @staticmethod
    def calculate_dynamic_efficiency(
        user_id,
        car_id=None,
        days_lookback=90,
        min_miles=50,
        min_kwh=20,
        charge_type_filter=None,  # e.g., 'AC'
        home_only=False
    ):
        """Observed mi/kWh from odometer deltas ÷ kWh delivered, with optional scoping."""
        cutoff = datetime.now().date() - timedelta(days=days_lookback)
        q = ChargingSession.query.filter(ChargingSession.user_id == user_id)
        if car_id:
            q = q.filter(ChargingSession.car_id == car_id)
        q = q.filter(ChargingSession.date >= cutoff)\
             .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
        if charge_type_filter:
            q = q.filter(ChargingSession.charge_type == charge_type_filter)

        sessions = q.all()
        if len(sessions) < 2:
            return None

        total_miles = 0.0
        total_kwh = 0.0
        prev_odo = None

        for s in sessions:
            # filter home-only if requested (use helper)
            if home_only and not DerivedMetricsService._is_home_like(s):
                # still advance odo if present for continuity
                if s.odometer is not None:
                    prev_odo = s.odometer if prev_odo is None else prev_odo
                continue

            # accumulate kWh (scoped)
            total_kwh += float(s.charge_delivered_kwh or 0)

            # build odometer windows (use all sessions for odo continuity)
            if s.odometer is not None:
                if prev_odo is None:
                    prev_odo = s.odometer
                else:
                    delta = s.odometer - prev_odo
                    # ignore negative/backwards jumps
                    if delta >= 0:
                        total_miles += delta
                        prev_odo = s.odometer
                    else:
                        prev_odo = s.odometer

        if total_miles >= min_miles and total_kwh >= min_kwh and total_kwh > 0:
            eff = total_miles / total_kwh
            # clamp to plausible band
            if eff < 1.0 or eff > 7.0:
                return None
            return round(eff, 2)
        return None

    @staticmethod
    def get_rolling_averages(user_id, car_id, days=30):
        """Get rolling averages for comparison with current session"""
        from datetime import datetime, timedelta
        
        date_from = datetime.now().date() - timedelta(days=days)
        
        query = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == car_id,
                ChargingSession.date >= date_from
            )
        )
        
        # Calculate averages
        result = query.with_entities(
            func.avg(ChargingSession.charge_delivered_kwh).label('avg_kwh'),
            func.avg(ChargingSession.cost_per_kwh).label('avg_cost_per_kwh'),
            func.avg(ChargingSession.duration_mins).label('avg_duration_mins')
        ).first()
        
        # Resolve efficiency (prefer dynamic)
        car = Car.query.get(car_id)
        efficiency, _, warning = DerivedMetricsService._resolve_efficiency(user_id, car)
        warnings = [warning] if warning else []
        
        avg_kwh = result.avg_kwh or 0
        avg_cost_per_kwh = result.avg_cost_per_kwh or 0
        avg_duration_mins = result.avg_duration_mins or 0
        
        # Derived values guarded against missing efficiency
        avg_total_cost = avg_kwh * avg_cost_per_kwh
        avg_miles_gained = (avg_kwh * efficiency) if efficiency else 0
        avg_cost_per_mile = (avg_total_cost / avg_miles_gained) if avg_miles_gained > 0 else 0
        avg_power_kw = (avg_kwh / (avg_duration_mins / 60)) if avg_duration_mins > 0 else 0
        
        return {
            'avg_kwh': avg_kwh,
            'avg_cost_per_kwh': avg_cost_per_kwh,
            'avg_total_cost': avg_total_cost,
            'avg_miles_gained': avg_miles_gained,
            'avg_cost_per_mile': avg_cost_per_mile,
            'avg_power_kw': avg_power_kw,
            'avg_duration_mins': avg_duration_mins,
            'warnings': warnings
        }

    @staticmethod
    def _calculate_daily_efficiency(user_id, date, car_id=None, anchor_horizon_days=10):
        """
        Observed mi/kWh for a specific date:
        - kWh = sum of charge_delivered_kwh on that date.
        - miles = odometer delta between nearest sessions before/after within ±anchor_horizon_days.
        Returns 0.0 if not enough anchors or kWh on day.
        """
        # kWh delivered on the day
        q_day = ChargingSession.query.filter_by(user_id=user_id, date=date)
        if car_id:
            q_day = q_day.filter_by(car_id=car_id)
        day_sessions = q_day.all()
        day_kwh = sum(float(s.charge_delivered_kwh or 0) for s in day_sessions)
        if day_kwh <= 0:
            return 0.0

        # nearest anchors within horizon
        start = date - timedelta(days=anchor_horizon_days)
        end = date + timedelta(days=anchor_horizon_days)
        base_q = ChargingSession.query.filter(
            and_(ChargingSession.user_id == user_id,
                 ChargingSession.date >= start,
                 ChargingSession.date <= end,
                 ChargingSession.odometer.isnot(None))
        )
        if car_id:
            base_q = base_q.filter(ChargingSession.car_id == car_id)

        before = (base_q.filter(ChargingSession.date <= date)
                          .order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
                          .first())
        after = (base_q.filter(ChargingSession.date >= date)
                         .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
                         .first())

        if not before or not after:
            return 0.0

        delta = float(after.odometer - before.odometer)
        if delta <= 0:
            return 0.0

        eff = delta / day_kwh
        if eff < 1.0 or eff > 7.0:
            return 0.0
        return round(eff, 2)
