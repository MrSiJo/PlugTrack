#!/usr/bin/env python3
"""
Test script for PlugTrack session chips and small charge handling
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.derived_metrics import DerivedMetricsService

def test_session_size_classification():
    """Test the session size classification function"""
    print("Testing session size classification...")
    
    # Test cases
    test_cases = [
        (15, "topup"),      # 15% should be topup
        (20, "topup"),      # 20% should be topup
        (25, "partial"),    # 25% should be partial
        (50, "partial"),    # 50% should be partial
        (55, "major"),      # 55% should be major
        (80, "major"),      # 80% should be major
    ]
    
    for delta_soc, expected in test_cases:
        result = DerivedMetricsService.classify_session_size(delta_soc)
        status = "✓" if result == expected else "✗"
        print(f"  {status} ΔSoC {delta_soc}% → {result} (expected: {expected})")
    
    print()

def test_low_confidence_detection():
    """Test the low confidence detection function"""
    print("Testing low confidence detection...")
    
    # Test cases
    test_cases = [
        (10, 2.5, True),   # 10 miles, 2.5 kWh → low confidence
        (15, 3.0, True),   # 15 miles, 3.0 kWh → low confidence (exactly at threshold)
        (16, 3.1, False),  # 16 miles, 3.1 kWh → high confidence
        (20, 2.0, True),   # 20 miles, 2.0 kWh → low confidence (low kWh)
        (25, 5.0, False),  # 25 miles, 5.0 kWh → high confidence
        (None, 3.0, True), # None miles, 3.0 kWh → low confidence
        (20, None, True),  # 20 miles, None kWh → low confidence
    ]
    
    for delta_miles, kwh, expected in test_cases:
        result = DerivedMetricsService.is_low_confidence(delta_miles, kwh)
        status = "✓" if result == expected else "✗"
        print(f"  {status} Δ{delta_miles or 'None'} mi, {kwh or 'None'} kWh → {result} (expected: {expected})")
    
    print()

def test_chip_selection_logic():
    """Test the chip selection logic (simulated)"""
    print("Testing chip selection logic...")
    
    # Simulate metrics data
    test_metrics = [
        {
            'name': 'High confidence session',
            'efficiency_used': 3.2,
            'cost_per_mile': 0.15,
            'threshold_ppm': 20.0,
            'is_cheaper_than_petrol': True,
            'avg_power_kw': 7.5,
            'percent_per_kwh': 8.2,
            'delta_miles': 25.0,
            'low_confidence': False
        },
        {
            'name': 'Low confidence session',
            'efficiency_used': 2.8,
            'cost_per_mile': 0.18,
            'threshold_ppm': 20.0,
            'is_cheaper_than_petrol': False,
            'avg_power_kw': 6.2,
            'percent_per_kwh': 7.8,
            'delta_miles': 12.0,
            'low_confidence': True
        },
        {
            'name': 'Free charging session',
            'efficiency_used': 3.5,
            'cost_per_mile': 0.0,
            'threshold_ppm': 0.0,
            'is_cheaper_than_petrol': None,
            'avg_power_kw': 8.0,
            'percent_per_kwh': 8.5,
            'delta_miles': 30.0,
            'low_confidence': False
        }
    ]
    
    for metrics in test_metrics:
        print(f"  {metrics['name']}:")
        
        # Priority 1: Efficiency chip
        if metrics['efficiency_used'] is not None:
            color_class = "green" if metrics['efficiency_used'] > 3.0 else "amber" if metrics['efficiency_used'] > 2.0 else "red"
            muted = " (muted)" if metrics['low_confidence'] else ""
            print(f"    - Efficiency: {metrics['efficiency_used']} mi/kWh {color_class}{muted}")
        
        # Priority 2: Cost per mile chip
        if metrics['cost_per_mile'] > 0:
            print(f"    - Cost: {metrics['cost_per_mile'] * 100:.1f}p/mi")
        else:
            print(f"    - Cost: 0.0p/mi (muted)")
        
        # Priority 3: Petrol comparison
        if metrics['threshold_ppm'] > 0 and metrics['is_cheaper_than_petrol'] is not None:
            symbol = "✓" if metrics['is_cheaper_than_petrol'] else "✖"
            status = "cheaper" if metrics['is_cheaper_than_petrol'] else "dearer"
            print(f"    - Petrol: {symbol} {status}")
        
        # Fillers
        if metrics['avg_power_kw'] > 0:
            print(f"    - Power: {metrics['avg_power_kw']} kW")
        if metrics['percent_per_kwh'] > 0:
            print(f"    - %/kWh: {metrics['percent_per_kwh']}%/kWh")
        
        print()

def main():
    """Run all tests"""
    print("PlugTrack Session Chips Test Suite")
    print("=" * 40)
    print()
    
    try:
        test_session_size_classification()
        test_low_confidence_detection()
        test_chip_selection_logic()
        
        print("All tests completed!")
        
    except Exception as e:
        print(f"Error running tests: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
