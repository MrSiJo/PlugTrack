#!/usr/bin/env python3
"""
Service for precomputing and storing session metrics in session_meta.
This ensures session detail pages load instantly without recomputation.
"""

import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session as DBSession
from datetime import datetime

from models.user import db
from models.charging_session import ChargingSession
from models.session_meta import SessionMeta
from models.car import Car
from services.derived_metrics import DerivedMetricsService


class SessionMetricsPrecomputeService:
    """Service for precomputing and storing session metrics"""
    
    # Metadata keys for storing precomputed metrics
    METADATA_KEYS = {
        'efficiency_used': 'efficiency_mi_kwh',
        'cost_per_mile': 'cost_per_mile_pence',
        'efficiency_confidence': 'confidence_level',
        'confidence_reasons': 'confidence_reasons',
        'dc_taper_flag': 'taper_detected',  # Map dc_taper_flag to taper_detected for spec compliance
        'mphc': 'miles_per_charging_hour',
        'total_cost': 'total_cost_gbp',
        'miles_gained': 'miles_gained',
        'battery_added_percent': 'battery_added_percent',
        'percent_per_kwh': 'percent_per_kwh',
        'avg_power_kw': 'avg_power_kw',
        'is_cheaper_than_petrol': 'is_cheaper_than_petrol',
        'efficiency_source': 'efficiency_source',
        'size_bucket': 'size_bucket',
        'last_computed': 'last_computed'
    }
    
    @staticmethod
    def precompute_session_metrics(session_id: int, force_recompute: bool = False) -> Dict[str, Any]:
        """
        Precompute and store metrics for a single session.
        
        Args:
            session_id: ID of the charging session
            force_recompute: If True, recompute even if already computed
            
        Returns:
            Dict containing the computed metrics
        """
        try:
            # Get the session
            session = ChargingSession.query.get(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")
            
            # Get the car
            car = Car.query.get(session.car_id)
            if not car:
                raise ValueError(f"Car {session.car_id} not found")
            
            # Check if already computed (unless forcing recompute)
            if not force_recompute:
                last_computed = SessionMeta.get_meta(session_id, SessionMetricsPrecomputeService.METADATA_KEYS['last_computed'])
                if last_computed:
                    # Return existing metrics
                    return SessionMetricsPrecomputeService._get_stored_metrics(session_id)
            
            # Compute metrics using DerivedMetricsService
            metrics = DerivedMetricsService.calculate_session_metrics(session, car)
            
            # Store metrics in session_meta
            SessionMetricsPrecomputeService._store_metrics(session_id, metrics)
            
            return metrics
            
        except Exception as e:
            raise Exception(f"Failed to precompute metrics for session {session_id}: {str(e)}")
    
    @staticmethod
    def precompute_all_sessions(user_id: int, car_id: Optional[int] = None, 
                               force_recompute: bool = False) -> Dict[str, Any]:
        """
        Precompute metrics for all sessions (or sessions for a specific car).
        
        Args:
            user_id: User ID to process sessions for
            car_id: Optional car ID to filter sessions
            force_recompute: If True, recompute even if already computed
            
        Returns:
            Dict containing summary of the operation
        """
        try:
            # Build query
            query = ChargingSession.query.filter_by(user_id=user_id)
            if car_id:
                query = query.filter_by(car_id=car_id)
            
            # Get all sessions
            sessions = query.all()
            
            if not sessions:
                return {
                    'success': True,
                    'message': 'No sessions found to process',
                    'total_sessions': 0,
                    'processed': 0,
                    'errors': []
                }
            
            processed = 0
            errors = []
            
            for session in sessions:
                try:
                    SessionMetricsPrecomputeService.precompute_session_metrics(
                        session.id, force_recompute=force_recompute
                    )
                    processed += 1
                except Exception as e:
                    errors.append({
                        'session_id': session.id,
                        'error': str(e)
                    })
            
            return {
                'success': len(errors) == 0,
                'message': f"Processed {processed} sessions with {len(errors)} errors",
                'total_sessions': len(sessions),
                'processed': processed,
                'errors': errors
            }
            
        except Exception as e:
            raise Exception(f"Failed to precompute all sessions: {str(e)}")
    
    @staticmethod
    def get_session_metrics(session_id: int) -> Dict[str, Any]:
        """
        Get precomputed metrics for a session.
        If not computed, computes them on-demand.
        
        Args:
            session_id: ID of the charging session
            
        Returns:
            Dict containing the metrics
        """
        try:
            # Try to get stored metrics first
            stored_metrics = SessionMetricsPrecomputeService._get_stored_metrics(session_id)
            if stored_metrics:
                return stored_metrics
            
            # If not stored, compute and store them
            return SessionMetricsPrecomputeService.precompute_session_metrics(session_id)
            
        except Exception as e:
            raise Exception(f"Failed to get metrics for session {session_id}: {str(e)}")
    
    @staticmethod
    def clear_session_metrics(session_id: int) -> bool:
        """
        Clear all precomputed metrics for a session.
        
        Args:
            session_id: ID of the charging session
            
        Returns:
            True if successful
        """
        try:
            for key in SessionMetricsPrecomputeService.METADATA_KEYS.values():
                SessionMeta.delete_meta(session_id, key)
            return True
        except Exception:
            return False
    
    @staticmethod
    def _store_metrics(session_id: int, metrics: Dict[str, Any]) -> None:
        """Store computed metrics in session_meta table"""
        
        # Store each metric
        for metric_key, meta_key in SessionMetricsPrecomputeService.METADATA_KEYS.items():
            if metric_key in metrics:
                value = metrics[metric_key]
                
                # Convert complex types to JSON strings
                if isinstance(value, (list, dict)):
                    value = json.dumps(value)
                elif isinstance(value, bool):
                    value = '1' if value else '0'
                elif value is not None:
                    value = str(value)
                else:
                    value = ''
                
                SessionMeta.set_meta(session_id, meta_key, value)
        
        # Store timestamp of computation
        SessionMeta.set_meta(session_id, 'last_computed', datetime.utcnow().isoformat())
    
    @staticmethod
    def _get_stored_metrics(session_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve stored metrics from session_meta table"""
        try:
            metrics = {}
            
            # Get each stored metric
            for metric_key, meta_key in SessionMetricsPrecomputeService.METADATA_KEYS.items():
                value = SessionMeta.get_meta(session_id, meta_key)
                
                if value is not None:
                                         # Convert back from stored format
                     if metric_key == 'confidence_reasons':
                         try:
                             metrics[metric_key] = json.loads(value) if value else []
                         except json.JSONDecodeError:
                             metrics[metric_key] = []
                     elif metric_key in ['dc_taper_flag', 'is_cheaper_than_petrol']:
                         metrics[metric_key] = value == '1'
                     elif metric_key in ['efficiency_used', 'cost_per_mile', 'total_cost', 'miles_gained', 
                                       'battery_added_percent', 'percent_per_kwh', 'avg_power_kw', 'mphc']:
                         try:
                             metrics[metric_key] = float(value) if value else None
                         except ValueError:
                             metrics[metric_key] = None
                     elif metric_key in ['efficiency_confidence', 'efficiency_source', 'size_bucket']:
                         metrics[metric_key] = value
                     elif metric_key == 'last_computed':
                         # Skip this internal field
                         continue
            
            return metrics if metrics else None
            
        except Exception:
            return None
    
    @staticmethod
    def get_metrics_summary(user_id: int, car_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get a summary of precomputed metrics status.
        
        Args:
            user_id: User ID to check
            car_id: Optional car ID to filter
            
        Returns:
            Dict containing summary information
        """
        try:
            # Build query
            query = ChargingSession.query.filter_by(user_id=user_id)
            if car_id:
                query = query.filter_by(car_id=car_id)
            
            total_sessions = query.count()
            
            # Count sessions with precomputed metrics
            sessions_with_metrics = 0
            sessions_without_metrics = 0
            
            for session in query.all():
                if SessionMeta.get_meta(session.id, 'last_computed'):
                    sessions_with_metrics += 1
                else:
                    sessions_without_metrics += 1
            
            return {
                'total_sessions': total_sessions,
                'sessions_with_metrics': sessions_with_metrics,
                'sessions_without_metrics': sessions_without_metrics,
                'completion_percentage': (sessions_with_metrics / total_sessions * 100) if total_sessions > 0 else 0
            }
            
        except Exception as e:
            raise Exception(f"Failed to get metrics summary: {str(e)}")
