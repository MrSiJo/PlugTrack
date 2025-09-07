"""
Session Metrics API Service for PlugTrack Phase 6 Stage E
Composes DerivedMetricsService, insights, and confidence data for session detail API.
"""

from typing import Dict, List, Optional, Any
from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from services.derived_metrics import DerivedMetricsService
from services.insights import InsightsService
from services.cost_parity import get_parity_comparison, ev_parity_rate_p_per_kwh


class SessionMetricsApiService:
    """Service for /api/session/<id>/metrics endpoint composition"""
    
    @staticmethod
    def get_session_metrics(session_id: int, user_id: int) -> Optional[Dict]:
        """
        Compose session metrics for API endpoint including:
        - DerivedMetricsService.calculate_session_metrics()
        - insights (loss %, home ROI delta, petrol parity snapshot)
        - confidence {level, reasons}
        - chips array ready for UI (max 6 objects)
        """
        # Get session and verify ownership
        session = ChargingSession.query.filter_by(id=session_id, user_id=user_id).first()
        if not session:
            return None
            
        # Get car for calculations
        car = Car.query.get(session.car_id)
        if not car:
            return None
        
        # Get base derived metrics
        metrics = DerivedMetricsService.calculate_session_metrics(session, car)
        
        # Calculate insights
        insights = SessionMetricsApiService._calculate_insights(session, car, metrics, user_id)
        
        # Calculate confidence
        confidence = SessionMetricsApiService._calculate_confidence(session, metrics)
        
        # Generate chips array for UI
        chips = SessionMetricsApiService._generate_chips_array(session, metrics, insights, confidence)
        
        # Generate summary (Stage F)
        summary = InsightsService.generate_summary(session_id)
        
        return {
            'session_id': session_id,
            'metrics': metrics,
            'insights': insights,
            'confidence': confidence,
            'chips': chips,
            'summary': summary
        }
    
    @staticmethod
    def _calculate_insights(session: ChargingSession, car: Car, metrics: Dict, user_id: int) -> Dict:
        """Calculate insights: loss %, home ROI delta, petrol parity snapshot"""
        insights = {}
        
        # Calculate loss estimate
        loss_percent = InsightsService.calculate_loss_estimate(session, car)
        insights['loss_percent'] = round(loss_percent, 1) if loss_percent is not None else None
        
        # Calculate home ROI delta
        home_roi_delta = InsightsService.calculate_home_roi_delta(session, metrics, user_id)
        insights['home_roi_delta_pence'] = round(home_roi_delta, 1) if home_roi_delta is not None else None
        
        # Calculate petrol parity snapshot
        insights['petrol_parity'] = SessionMetricsApiService._calculate_petrol_parity(session, car, metrics, user_id)
        
        return insights
    
    @staticmethod
    def _calculate_petrol_parity(session: ChargingSession, car: Car, metrics: Dict, user_id: int) -> Optional[Dict]:
        """Calculate petrol parity comparison for this session"""
        if not metrics.get('efficiency_used') or not session.cost_per_kwh:
            return None
        
        # Get user settings for petrol price and MPG
        petrol_ppl = Settings.get_setting(user_id, 'petrol_ppl')
        mpg_uk = Settings.get_setting(user_id, 'mpg_uk')
        
        if not petrol_ppl or not mpg_uk:
            return None
        
        try:
            petrol_ppl = float(petrol_ppl)
            mpg_uk = float(mpg_uk)
        except (ValueError, TypeError):
            return None
        
        # Calculate EV parity rate
        parity_rate_p_per_kwh = ev_parity_rate_p_per_kwh(
            petrol_ppl, 
            mpg_uk, 
            metrics['efficiency_used']
        )
        
        if parity_rate_p_per_kwh is None:
            return None
        
        # Session effective rate in p/kWh
        session_rate_p_per_kwh = session.cost_per_kwh * 100
        
        # Get comparison
        comparison = get_parity_comparison(session_rate_p_per_kwh, parity_rate_p_per_kwh)
        
        return {
            'session_rate_p_per_kwh': round(session_rate_p_per_kwh, 1),
            'parity_rate_p_per_kwh': round(parity_rate_p_per_kwh, 1),
            'status': comparison['status'],  # 'cheaper', 'dearer', 'unknown'
            'label': comparison['label'],
            'tooltip': comparison['tooltip']
        }
    
    @staticmethod
    def _calculate_confidence(session: ChargingSession, metrics: Dict) -> Dict:
        """Calculate confidence level and reasons"""
        level = 'high'
        reasons = []
        
        # Check for low confidence indicators
        if metrics.get('low_confidence'):
            level = 'low'
            reasons.append('Small charging window')
        
        # Check for missing data
        if not session.odometer:
            level = 'medium' if level == 'high' else 'low'
            reasons.append('No odometer data')
        
        if not metrics.get('efficiency_used'):
            level = 'medium' if level == 'high' else 'low'
            reasons.append('No efficiency data')
        
        if session.cost_per_kwh <= 0:
            if 'No cost data' not in reasons:
                reasons.append('Free session - no cost analysis')
        
        # Check for baseline session
        if session.is_baseline:
            level = 'medium' if level == 'high' else level
            reasons.append('Baseline session')
        
        # Check for small energy delivery
        if session.charge_delivered_kwh < 3.0:
            level = 'medium' if level == 'high' else 'low'
            reasons.append('Small energy delivery')
        
        # If no issues found, add positive reasons
        if level == 'high' and not reasons:
            if session.odometer and metrics.get('efficiency_used'):
                reasons.append('Complete data available')
            if session.charge_delivered_kwh >= 10:
                reasons.append('Substantial charging session')
        
        return {
            'level': level,
            'reasons': reasons
        }
    
    @staticmethod
    def _generate_chips_array(session: ChargingSession, metrics: Dict, insights: Dict, confidence: Dict) -> List[Dict]:
        """Generate chips array for UI (max 6 objects with style, icon, text format for template)"""
        chips = []
        
        # 1. Efficiency chip (if available)
        if metrics.get('efficiency_used') is not None and metrics['efficiency_used'] > 0:
            tone = SessionMetricsApiService._get_efficiency_tone(metrics['efficiency_used'])
            chips.append({
                'style': SessionMetricsApiService._tone_to_style(tone),
                'icon': 'speedometer2',
                'text': f"Efficiency: {metrics['efficiency_used']:.1f} mi/kWh"
            })
        
        # 2. Cost per mile chip (if paid session)
        if metrics.get('cost_per_mile') and session.cost_per_kwh > 0:
            cost_pence = metrics['cost_per_mile'] * 100
            tone = SessionMetricsApiService._get_cost_tone(cost_pence)
            chips.append({
                'style': SessionMetricsApiService._tone_to_style(tone),
                'icon': 'cash-coin',
                'text': f"Cost/Mile: {cost_pence:.1f}p"
            })
        
        # 3. Petrol parity chip (if available)
        if insights.get('petrol_parity'):
            parity = insights['petrol_parity']
            tone = 'positive' if parity['status'] == 'cheaper' else 'negative'
            chips.append({
                'style': SessionMetricsApiService._tone_to_style(tone),
                'icon': 'fuel-pump',
                'text': f"vs Petrol: {parity['label']}"
            })
        
        # 4. Loss estimate chip (if available)
        if insights.get('loss_percent') is not None:
            loss = insights['loss_percent']
            tone = SessionMetricsApiService._get_loss_tone(loss)
            loss_value = f"{abs(loss):.1f}%" if loss != 0 else "0%"
            chips.append({
                'style': SessionMetricsApiService._tone_to_style(tone),
                'icon': 'battery-half',
                'text': f"Loss Est.: {loss_value}"
            })
        
        # 5. Home ROI delta chip (if available and this isn't a home session)
        if insights.get('home_roi_delta_pence') is not None:
            delta = insights['home_roi_delta_pence']
            tone = 'negative' if delta > 0 else 'positive'
            delta_value = f"+{delta:.0f}p" if delta > 0 else f"{delta:.0f}p"
            chips.append({
                'style': SessionMetricsApiService._tone_to_style(tone),
                'icon': 'house',
                'text': f"vs Home: {delta_value}"
            })
        
        # 6. Session size chip
        delta_soc = session.soc_to - session.soc_from
        session_size = DerivedMetricsService.classify_session_size(delta_soc)
        tone = SessionMetricsApiService._get_session_size_tone(session_size)
        chips.append({
            'style': SessionMetricsApiService._tone_to_style(tone),
            'icon': 'battery-charging',
            'text': f"Size: {session_size.title()}"
        })
        
        # Limit to max 6 chips and prioritize by importance
        return chips[:6]
    
    @staticmethod
    def _get_efficiency_tone(efficiency: float) -> str:
        """Get tone for efficiency value"""
        if efficiency >= 4.5:
            return 'positive'
        elif efficiency >= 3.0:
            return 'neutral'
        else:
            return 'negative'
    
    @staticmethod
    def _get_cost_tone(cost_pence: float) -> str:
        """Get tone for cost per mile value"""
        if cost_pence <= 5.0:
            return 'positive'
        elif cost_pence <= 10.0:
            return 'neutral'
        else:
            return 'negative'
    
    @staticmethod
    def _get_loss_tone(loss_percent: float) -> str:
        """Get tone for loss percentage"""
        if loss_percent <= 5:
            return 'positive'
        elif loss_percent <= 15:
            return 'neutral'
        else:
            return 'negative'
    
    @staticmethod
    def _get_session_size_tone(session_size: str) -> str:
        """Get tone for session size"""
        if session_size == 'major':
            return 'positive'
        elif session_size == 'partial':
            return 'neutral'
        else:  # topup
            return 'info'
    
    @staticmethod
    def _tone_to_style(tone: str) -> str:
        """Convert tone to Bootstrap chip style class"""
        tone_mapping = {
            'positive': 'success',
            'negative': 'danger', 
            'neutral': 'warning',
            'info': 'info'
        }
        return tone_mapping.get(tone, 'secondary')
