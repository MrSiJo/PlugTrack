"""
Confidence UI Service for PlugTrack Phase 6 P6-3
Converts technical confidence reasons into user-friendly explanations.
"""

from typing import Dict, List, Optional


class ConfidenceUiService:
    """Service for converting technical confidence data into user-friendly UI elements"""
    
    # Mapping technical reasons to user-friendly explanations
    REASON_MAPPINGS = {
        # Technical backend reasons
        'small_window': 'Short trip between charges',
        'stale_anchors': 'Long gap since last reading',
        'outlier_clamped': 'Unusual efficiency reading',
        'outlier': 'Unusual efficiency reading',
        
        # Session metrics API reasons
        'Small charging window': 'Short trip between charges',
        'No odometer data': 'Missing mileage reading',
        'No efficiency data': 'Unable to calculate efficiency',
        'Free session - no cost analysis': 'Free charging session',
        'Baseline session': 'Initial setup session',
        'Small energy delivery': 'Very small charge amount',
        
        # Positive reasons
        'Complete data available': 'All data available',
        'Substantial charging session': 'Good charging amount',
    }
    
    # Enhanced explanations for tooltips/help text
    REASON_EXPLANATIONS = {
        'Short trip between charges': 'The trip since your last charge was very short, making efficiency calculations less reliable.',
        'Long gap since last reading': 'It\'s been a while since your last odometer reading, which may affect accuracy.',
        'Unusual efficiency reading': 'The calculated efficiency seems unusually high or low and has been adjusted.',
        'Missing mileage reading': 'No odometer reading was recorded for this session.',
        'Unable to calculate efficiency': 'Not enough data to determine how efficiently you\'re driving.',
        'Free charging session': 'This was a free charge, so cost analysis isn\'t applicable.',
        'Initial setup session': 'This is one of your first sessions used to calibrate the system.',
        'Very small charge amount': 'This was a very small top-up, making calculations less meaningful.',
        'All data available': 'Complete odometer and charging data makes calculations very reliable.',
        'Good charging amount': 'Substantial energy delivered makes calculations more accurate.',
    }
    
    # Confidence level descriptions
    LEVEL_DESCRIPTIONS = {
        'high': {
            'description': 'Reliable Data',
            'explanation': 'All necessary data is available and calculations are trustworthy.',
            'icon': 'bi-shield-check',
            'color': 'success'
        },
        'medium': {
            'description': 'Some Limitations',
            'explanation': 'Most data is available but there are minor issues that may affect accuracy.',
            'icon': 'bi-shield-exclamation',
            'color': 'warning'
        },
        'low': {
            'description': 'Limited Data',
            'explanation': 'Several data issues mean calculations should be taken with caution.',
            'icon': 'bi-shield-x',
            'color': 'danger'
        }
    }
    
    @staticmethod
    def get_user_friendly_confidence(confidence_data: Dict) -> Dict:
        """
        Convert technical confidence data to user-friendly format.
        
        Args:
            confidence_data: Dict with 'level' and 'reasons' keys
            
        Returns:
            Dict with user-friendly confidence information
        """
        if not confidence_data or not isinstance(confidence_data, dict):
            return ConfidenceUiService._get_default_confidence()
        
        level = confidence_data.get('level', 'medium')
        technical_reasons = confidence_data.get('reasons', [])
        
        # Convert technical reasons to user-friendly ones
        friendly_reasons = []
        detailed_explanations = []
        
        for reason in technical_reasons:
            # Handle technical reasons that may include parameters (e.g., "small_window (Δ15.0 mi ≤ 15)")
            # Extract the base reason
            base_reason = reason.split('(')[0].strip()
            
            # Map to user-friendly text
            friendly_reason = ConfidenceUiService.REASON_MAPPINGS.get(
                base_reason, 
                ConfidenceUiService.REASON_MAPPINGS.get(reason, reason.replace('_', ' ').title())
            )
            
            # Get detailed explanation
            explanation = ConfidenceUiService.REASON_EXPLANATIONS.get(
                friendly_reason,
                f"Technical: {reason}"
            )
            
            if friendly_reason not in friendly_reasons:
                friendly_reasons.append(friendly_reason)
                detailed_explanations.append({
                    'reason': friendly_reason,
                    'explanation': explanation
                })
        
        # Get level information
        level_info = ConfidenceUiService.LEVEL_DESCRIPTIONS.get(level, 
            ConfidenceUiService.LEVEL_DESCRIPTIONS['medium'])
        
        return {
            'level': level,
            'level_description': level_info['description'],
            'level_explanation': level_info['explanation'],
            'level_icon': level_info['icon'],
            'level_color': level_info['color'],
            'friendly_reasons': friendly_reasons,
            'detailed_explanations': detailed_explanations,
            'has_issues': len(friendly_reasons) > 0 and level != 'high',
            'original': confidence_data  # Keep original for debugging
        }
    
    @staticmethod
    def _get_default_confidence() -> Dict:
        """Return default confidence when no data is available"""
        return {
            'level': 'medium',
            'level_description': 'Unknown',
            'level_explanation': 'Confidence information not available.',
            'level_icon': 'bi-shield-question',
            'level_color': 'secondary',
            'friendly_reasons': ['Confidence data unavailable'],
            'detailed_explanations': [{
                'reason': 'Confidence data unavailable',
                'explanation': 'Unable to determine data quality for this session.'
            }],
            'has_issues': True,
            'original': {}
        }
    
    @staticmethod
    def get_confidence_badge_html(confidence_data: Dict, size: str = 'normal') -> str:
        """
        Generate HTML for confidence badge.
        
        Args:
            confidence_data: Confidence data (will be converted to user-friendly)
            size: 'small', 'normal', or 'large'
            
        Returns:
            HTML string for confidence badge
        """
        friendly = ConfidenceUiService.get_user_friendly_confidence(confidence_data)
        
        size_classes = {
            'small': 'badge-sm',
            'normal': '',
            'large': 'badge-lg fs-6'
        }
        
        size_class = size_classes.get(size, '')
        
        return f'''
        <span class="badge bg-{friendly['level_color']} {size_class}" 
              title="{friendly['level_explanation']}"
              data-bs-toggle="tooltip">
            <i class="{friendly['level_icon']} me-1"></i>
            {friendly['level_description']}
        </span>
        '''
    
    @staticmethod
    def get_confidence_card_html(confidence_data: Dict) -> str:
        """
        Generate HTML for detailed confidence card.
        
        Args:
            confidence_data: Confidence data (will be converted to user-friendly)
            
        Returns:
            HTML string for confidence card content
        """
        friendly = ConfidenceUiService.get_user_friendly_confidence(confidence_data)
        
        # Build reasons list
        reasons_html = ''
        if friendly['detailed_explanations']:
            reasons_html = '<ul class="mb-0">'
            for item in friendly['detailed_explanations']:
                reasons_html += f'''
                <li class="mb-2">
                    <strong>{item['reason']}</strong><br>
                    <small class="text-muted">{item['explanation']}</small>
                </li>
                '''
            reasons_html += '</ul>'
        else:
            reasons_html = '<p class="text-muted mb-0">No specific issues detected.</p>'
        
        return f'''
        <div class="d-flex align-items-center mb-3">
            <i class="{friendly['level_icon']} text-{friendly['level_color']} me-2" style="font-size: 1.5rem;"></i>
            <div>
                <h6 class="mb-0">{friendly['level_description']}</h6>
                <small class="text-muted">{friendly['level_explanation']}</small>
            </div>
        </div>
        
        {reasons_html}
        '''
