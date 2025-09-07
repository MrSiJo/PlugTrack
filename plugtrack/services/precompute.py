"""
Precompute service for derived metrics.
Calculates and stores computed fields for charging sessions to improve performance.
"""

from models.user import db
from models.charging_session import ChargingSession
from models.car import Car
from services.derived_metrics import DerivedMetricsService
from services.insights import InsightsService
from flask import current_app


class PrecomputeService:
    """Service for precomputing derived metrics for charging sessions."""
    
    @staticmethod
    def compute_for_session(session_id):
        """
        Compute and store derived metrics for a specific session.
        
        Args:
            session_id (int): ID of the charging session to compute metrics for
            
        Returns:
            dict: Result with success status and computed metrics or error message
        """
        try:
            # Get the session
            session = ChargingSession.query.get(session_id)
            if not session:
                return {
                    'success': False,
                    'error': f'Session {session_id} not found'
                }
            
            # Get the car
            car = Car.query.get(session.car_id)
            if not car:
                return {
                    'success': False,
                    'error': f'Car {session.car_id} not found for session {session_id}'
                }
            
            # Calculate metrics using existing DerivedMetricsService
            metrics = DerivedMetricsService.calculate_session_metrics(session, car)
            
            # Extract the specific metrics we want to precompute
            efficiency_mpkwh = metrics.get('efficiency_used')
            cost_per_mile = metrics.get('cost_per_mile', 0)
            loss_estimate = metrics.get('loss_estimate', 0)
            
            # Convert cost per mile to pence per mile
            pence_per_mile = cost_per_mile * 100 if cost_per_mile else 0
            
            # Update the session with computed values
            session.computed_efficiency_mpkwh = efficiency_mpkwh
            session.computed_pence_per_mile = pence_per_mile
            session.computed_loss_pct = loss_estimate
            
            # Commit the changes
            db.session.commit()
            
            current_app.logger.info(f"Precomputed metrics for session {session_id}: "
                                  f"efficiency={efficiency_mpkwh}, pence_per_mile={pence_per_mile}, loss_pct={loss_estimate}")
            
            return {
                'success': True,
                'session_id': session_id,
                'metrics': {
                    'efficiency_mpkwh': efficiency_mpkwh,
                    'pence_per_mile': pence_per_mile,
                    'loss_pct': loss_estimate
                }
            }
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error precomputing metrics for session {session_id}: {e}")
            return {
                'success': False,
                'error': f'Failed to compute metrics: {str(e)}'
            }
    
    @staticmethod
    def compute_for_user(user_id, car_id=None, force_recompute=False):
        """
        Compute derived metrics for all sessions belonging to a user.
        
        Args:
            user_id (int): ID of the user
            car_id (int, optional): Specific car ID to filter by
            force_recompute (bool): Whether to recompute even if already computed
            
        Returns:
            dict: Result with success status and summary statistics
        """
        try:
            # Build query
            query = ChargingSession.query.filter_by(user_id=user_id)
            if car_id:
                query = query.filter_by(car_id=car_id)
            
            # Filter out already computed sessions unless force recompute
            if not force_recompute:
                query = query.filter(
                    (ChargingSession.computed_efficiency_mpkwh.is_(None)) |
                    (ChargingSession.computed_pence_per_mile.is_(None)) |
                    (ChargingSession.computed_loss_pct.is_(None))
                )
            
            sessions = query.all()
            
            if not sessions:
                return {
                    'success': True,
                    'message': 'No sessions to compute',
                    'total_sessions': 0,
                    'processed': 0,
                    'errors': []
                }
            
            processed = 0
            errors = []
            
            for session in sessions:
                result = PrecomputeService.compute_for_session(session.id)
                if result['success']:
                    processed += 1
                else:
                    errors.append({
                        'session_id': session.id,
                        'error': result['error']
                    })
            
            current_app.logger.info(f"Precomputed metrics for user {user_id}: "
                                  f"{processed}/{len(sessions)} sessions processed")
            
            return {
                'success': True,
                'message': f'Processed {processed} of {len(sessions)} sessions',
                'total_sessions': len(sessions),
                'processed': processed,
                'errors': errors
            }
            
        except Exception as e:
            current_app.logger.error(f"Error precomputing metrics for user {user_id}: {e}")
            return {
                'success': False,
                'error': f'Failed to compute metrics for user: {str(e)}'
            }
    
    @staticmethod
    def compute_all(force_recompute=False):
        """
        Compute derived metrics for all sessions in the database.
        
        Args:
            force_recompute (bool): Whether to recompute even if already computed
            
        Returns:
            dict: Result with success status and summary statistics
        """
        try:
            # Build query
            query = ChargingSession.query
            
            # Filter out already computed sessions unless force recompute
            if not force_recompute:
                query = query.filter(
                    (ChargingSession.computed_efficiency_mpkwh.is_(None)) |
                    (ChargingSession.computed_pence_per_mile.is_(None)) |
                    (ChargingSession.computed_loss_pct.is_(None))
                )
            
            sessions = query.all()
            
            if not sessions:
                return {
                    'success': True,
                    'message': 'No sessions to compute',
                    'total_sessions': 0,
                    'processed': 0,
                    'errors': []
                }
            
            processed = 0
            errors = []
            
            for session in sessions:
                result = PrecomputeService.compute_for_session(session.id)
                if result['success']:
                    processed += 1
                else:
                    errors.append({
                        'session_id': session.id,
                        'error': result['error']
                    })
            
            current_app.logger.info(f"Precomputed metrics for all sessions: "
                                  f"{processed}/{len(sessions)} sessions processed")
            
            return {
                'success': True,
                'message': f'Processed {processed} of {len(sessions)} sessions',
                'total_sessions': len(sessions),
                'processed': processed,
                'errors': errors
            }
            
        except Exception as e:
            current_app.logger.error(f"Error precomputing metrics for all sessions: {e}")
            return {
                'success': False,
                'error': f'Failed to compute metrics for all sessions: {str(e)}'
            }
    
    @staticmethod
    def get_metrics_summary(user_id=None, car_id=None):
        """
        Get summary of computed metrics status.
        
        Args:
            user_id (int, optional): ID of the user. If None, returns global summary.
            car_id (int, optional): Specific car ID to filter by
            
        Returns:
            dict: Summary statistics
        """
        try:
            # Build query
            query = ChargingSession.query
            if user_id:
                query = query.filter_by(user_id=user_id)
            if car_id:
                query = query.filter_by(car_id=car_id)
            
            total_sessions = query.count()
            
            # Count sessions with all metrics computed
            sessions_with_metrics = query.filter(
                ChargingSession.computed_efficiency_mpkwh.isnot(None),
                ChargingSession.computed_pence_per_mile.isnot(None),
                ChargingSession.computed_loss_pct.isnot(None)
            ).count()
            
            sessions_without_metrics = total_sessions - sessions_with_metrics
            completion_percentage = (sessions_with_metrics / total_sessions * 100) if total_sessions > 0 else 0
            
            return {
                'success': True,
                'total_sessions': total_sessions,
                'computed_sessions': sessions_with_metrics,
                'pending_sessions': sessions_without_metrics,
                'completion_rate': completion_percentage
            }
            
        except Exception as e:
            current_app.logger.error(f"Error getting metrics summary: {e}")
            return {
                'success': False,
                'error': str(e)
            }
