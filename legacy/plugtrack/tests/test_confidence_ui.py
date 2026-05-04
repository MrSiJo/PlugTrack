"""
Unit tests for ConfidenceUiService
Tests the conversion of technical confidence data to user-friendly formats.
"""

import unittest
from services.confidence_ui import ConfidenceUiService


class TestConfidenceUiService(unittest.TestCase):
    """Test the ConfidenceUiService for P6-3 implementation"""
    
    def test_get_user_friendly_confidence_high_quality(self):
        """Test conversion of high confidence data"""
        technical_data = {
            'level': 'high',
            'reasons': ['Complete data available', 'Substantial charging session']
        }
        
        result = ConfidenceUiService.get_user_friendly_confidence(technical_data)
        
        self.assertEqual(result['level'], 'high')
        self.assertEqual(result['level_description'], 'Reliable Data')
        self.assertEqual(result['level_icon'], 'bi-shield-check')
        self.assertEqual(result['level_color'], 'success')
        self.assertFalse(result['has_issues'])
        self.assertIn('All data available', result['friendly_reasons'])
        self.assertIn('Good charging amount', result['friendly_reasons'])
    
    def test_get_user_friendly_confidence_low_quality(self):
        """Test conversion of low confidence data with technical reasons"""
        technical_data = {
            'level': 'low',
            'reasons': [
                'small_window (Δ10.5 mi ≤ 15)',
                'stale_anchors (15 days > 10)',
                'No odometer data'
            ]
        }
        
        result = ConfidenceUiService.get_user_friendly_confidence(technical_data)
        
        self.assertEqual(result['level'], 'low')
        self.assertEqual(result['level_description'], 'Limited Data')
        self.assertEqual(result['level_icon'], 'bi-shield-x')
        self.assertEqual(result['level_color'], 'danger')
        self.assertTrue(result['has_issues'])
        self.assertIn('Short trip between charges', result['friendly_reasons'])
        self.assertIn('Long gap since last reading', result['friendly_reasons'])
        self.assertIn('Missing mileage reading', result['friendly_reasons'])
        
        # Check detailed explanations
        explanations = [item['reason'] for item in result['detailed_explanations']]
        self.assertIn('Short trip between charges', explanations)
        self.assertIn('Long gap since last reading', explanations)
        self.assertIn('Missing mileage reading', explanations)
    
    def test_get_user_friendly_confidence_medium_quality(self):
        """Test conversion of medium confidence data"""
        technical_data = {
            'level': 'medium',
            'reasons': ['Small energy delivery', 'Free session - no cost analysis']
        }
        
        result = ConfidenceUiService.get_user_friendly_confidence(technical_data)
        
        self.assertEqual(result['level'], 'medium')
        self.assertEqual(result['level_description'], 'Some Limitations')
        self.assertEqual(result['level_icon'], 'bi-shield-exclamation')
        self.assertEqual(result['level_color'], 'warning')
        self.assertTrue(result['has_issues'])
        self.assertIn('Very small charge amount', result['friendly_reasons'])
        self.assertIn('Free charging session', result['friendly_reasons'])
    
    def test_get_user_friendly_confidence_outlier_clamped(self):
        """Test handling of outlier clamped reasons"""
        technical_data = {
            'level': 'medium',
            'reasons': ['outlier_clamped (8.5 mi/kWh ≥ 7.0)']
        }
        
        result = ConfidenceUiService.get_user_friendly_confidence(technical_data)
        
        self.assertIn('Unusual efficiency reading', result['friendly_reasons'])
        explanations = [item['explanation'] for item in result['detailed_explanations']]
        self.assertTrue(any('unusually high or low' in exp for exp in explanations))
    
    def test_get_user_friendly_confidence_empty_data(self):
        """Test handling of empty or None confidence data"""
        result = ConfidenceUiService.get_user_friendly_confidence(None)
        
        self.assertEqual(result['level'], 'medium')
        self.assertEqual(result['level_description'], 'Unknown')
        self.assertTrue(result['has_issues'])
        self.assertIn('Confidence data unavailable', result['friendly_reasons'])
    
    def test_get_user_friendly_confidence_unknown_reasons(self):
        """Test handling of unknown technical reasons"""
        technical_data = {
            'level': 'low',
            'reasons': ['some_unknown_technical_reason', 'another_weird_issue']
        }
        
        result = ConfidenceUiService.get_user_friendly_confidence(technical_data)
        
        # Should gracefully handle unknown reasons
        self.assertEqual(result['level'], 'low')
        self.assertTrue(len(result['friendly_reasons']) >= 2)
        
        # Unknown reasons should be cleaned up (underscores replaced, title case)
        friendly_reasons_text = ' '.join(result['friendly_reasons'])
        self.assertNotIn('_', friendly_reasons_text)
    
    def test_get_confidence_badge_html(self):
        """Test HTML generation for confidence badge"""
        technical_data = {
            'level': 'high',
            'reasons': ['Complete data available']
        }
        
        html = ConfidenceUiService.get_confidence_badge_html(technical_data, size='normal')
        
        self.assertIn('badge bg-success', html)
        self.assertIn('bi-shield-check', html)
        self.assertIn('Reliable Data', html)
        self.assertIn('data-bs-toggle="tooltip"', html)
    
    def test_get_confidence_card_html(self):
        """Test HTML generation for confidence card"""
        technical_data = {
            'level': 'medium',
            'reasons': ['Small energy delivery', 'No efficiency data']
        }
        
        html = ConfidenceUiService.get_confidence_card_html(technical_data)
        
        self.assertIn('bi-shield-exclamation', html)
        self.assertIn('text-warning', html)
        self.assertIn('Some Limitations', html)
        self.assertIn('Very small charge amount', html)
        self.assertIn('Unable to calculate efficiency', html)
        self.assertIn('<ul class="mb-0">', html)
    
    def test_get_confidence_card_html_no_issues(self):
        """Test HTML generation for high confidence with no issues"""
        technical_data = {
            'level': 'high',
            'reasons': []
        }
        
        html = ConfidenceUiService.get_confidence_card_html(technical_data)
        
        self.assertIn('alert alert-success', html)
        self.assertIn('All data looks good', html)
        self.assertIn('bi-check-circle', html)


if __name__ == '__main__':
    unittest.main()
