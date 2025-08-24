from models.charging_session import ChargingSession
from models.car import Car
from models.settings import Settings
from models.session_meta import SessionMeta
from datetime import datetime, timedelta
from sqlalchemy import and_, or_

class HintsService:
    """Service for generating smart hints and recommendations for charging sessions"""
    
    @staticmethod
    def get_session_hints(session, car):
        """Get all applicable hints for a charging session"""
        hints = []
        
        # Check if hints are dismissed
        dismissed_hints = SessionMeta.get_meta(session.id, 'dismissed_hints', '')
        dismissed_codes = dismissed_hints.split(',') if dismissed_hints else []
        
        # Generate hints
        hints.extend(HintsService._get_dc_taper_hints(session, dismissed_codes))
        hints.extend(HintsService._get_finish_at_home_hints(session, dismissed_codes))
        hints.extend(HintsService._get_storage_soc_hints(session, car, dismissed_codes))
        hints.extend(HintsService._get_full_charge_hints(session, car, dismissed_codes))
        
        return hints
    
    @staticmethod
    def _get_dc_taper_hints(session, dismissed_codes):
        """Generate DC taper hints"""
        hints = []
        
        if 'dc_taper' not in dismissed_codes and session.charge_type == 'DC' and session.soc_to > 65:
            hints.append({
                'code': 'dc_taper',
                'type': 'warning',
                'title': 'DC Taper Likely',
                'message': 'Taper likely above ~65%—stop earlier and finish at home.',
                'icon': 'bi-lightning-charge',
                'dismissible': True
            })
        
        return hints
    
    @staticmethod
    def _get_finish_at_home_hints(session, dismissed_codes):
        """Generate finish at home hints"""
        hints = []
        
        if 'finish_at_home' not in dismissed_codes and not session.is_home_charging:
            # Get home reference rate
            home_rate = float(Settings.get_setting(session.user_id, 'home_rate_p_per_kwh', '20.0')) / 100  # Convert p/kWh to £/kWh
            
            if session.cost_per_kwh >= (2 * home_rate) and session.soc_to >= 60:
                hints.append({
                    'code': 'finish_at_home',
                    'type': 'info',
                    'title': 'Finish at Home',
                    'message': f'Finishing at home likely cheaper (home: {home_rate:.2f}£/kWh vs {session.cost_per_kwh:.2f}£/kWh).',
                    'icon': 'bi-house',
                    'dismissible': True
                })
        
        return hints
    
    @staticmethod
    def _get_storage_soc_hints(session, car, dismissed_codes):
        """Generate storage SoC hints"""
        hints = []
        
        if 'storage_soc' not in dismissed_codes:
            # Check if car has been parked for >7 days
            last_drive_date = HintsService._get_last_drive_date(session.user_id, car.id)
            
            if last_drive_date and session.date > last_drive_date + timedelta(days=7) and session.soc_to < 40:
                hints.append({
                    'code': 'storage_soc',
                    'type': 'info',
                    'title': 'Storage SoC',
                    'message': 'Consider topping to 50–60% for storage when parked long-term.',
                    'icon': 'bi-battery-half',
                    'dismissible': True
                })
        
        return hints
    
    @staticmethod
    def _get_full_charge_hints(session, car, dismissed_codes):
        """Generate 100% charge hints"""
        hints = []
        
        if 'full_charge_due' not in dismissed_codes and car.recommended_full_charge_enabled:
            # Check if it's time for a full charge
            last_full_charge = HintsService._get_last_full_charge_date(session.user_id, car.id)
            
            if last_full_charge:
                # Calculate days since last full charge
                days_since = (session.date - last_full_charge).days
                
                # Get frequency threshold
                frequency_value = car.recommended_full_charge_frequency_value or 30
                frequency_unit = car.recommended_full_charge_frequency_unit or 'days'
                
                # Convert to days
                if frequency_unit == 'months':
                    threshold_days = frequency_value * 30
                else:
                    threshold_days = frequency_value
                
                if days_since >= threshold_days:
                    hints.append({
                        'code': 'full_charge_due',
                        'type': 'warning',
                        'title': 'Full Balance Charge Due',
                        'message': f'Monthly 100% balance charge due (last: {days_since} days ago).',
                        'icon': 'bi-battery-charging',
                        'dismissible': True
                    })
        
        return hints
    
    @staticmethod
    def _get_last_drive_date(user_id, car_id):
        """Get the date of the last drive (session with odometer change)"""
        # This is a simplified implementation - in a real system you might track actual drives
        # For now, we'll use the last charging session date as a proxy
        last_session = ChargingSession.query.filter_by(
            user_id=user_id, 
            car_id=car_id
        ).order_by(ChargingSession.date.desc()).first()
        
        return last_session.date if last_session else None
    
    @staticmethod
    def _get_last_full_charge_date(user_id, car_id):
        """Get the date of the last full charge (soc_to >= 99)"""
        last_full_charge = ChargingSession.query.filter(
            and_(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == car_id,
                ChargingSession.soc_to >= 99
            )
        ).order_by(ChargingSession.date.desc()).first()
        
        return last_full_charge.date if last_full_charge else None
    
    @staticmethod
    def dismiss_hint(session_id, hint_code):
        """Dismiss a hint for a session"""
        # Get current dismissed hints
        dismissed_hints = SessionMeta.get_meta(session_id, 'dismissed_hints', '')
        dismissed_codes = dismissed_hints.split(',') if dismissed_hints else []
        
        # Add new code if not already present
        if hint_code not in dismissed_codes:
            dismissed_codes.append(hint_code)
            # Remove empty strings
            dismissed_codes = [code for code in dismissed_codes if code.strip()]
            
            # Save updated list
            SessionMeta.set_meta(session_id, 'dismissed_hints', ','.join(dismissed_codes))
        
        return True
    
    @staticmethod
    def restore_hint(session_id, hint_code):
        """Restore a dismissed hint for a session"""
        # Get current dismissed hints
        dismissed_hints = SessionMeta.get_meta(session_id, 'dismissed_hints', '')
        dismissed_codes = dismissed_hints.split(',') if dismissed_hints else []
        
        # Remove the code
        if hint_code in dismissed_codes:
            dismissed_codes.remove(hint_code)
            
            # Save updated list
            if dismissed_codes:
                SessionMeta.set_meta(session_id, 'dismissed_hints', ','.join(dismissed_codes))
            else:
                SessionMeta.delete_meta(session_id, 'dismissed_hints')
        
        return True
