# PlugTrack Session Chips & Small Charge Handling

This document describes the implementation of session chips and "small charge" handling in PlugTrack, which addresses the issue of tiny top-ups looking inefficient and visually noisy in the UI.

## Overview

The system implements:
- **Inline chips** (max 3) on the session list for quick insights
- **Full insight set** in the Details drawer
- **Low-confidence detection** for tiny windows
- **kWh-weighted analytics** for stable metrics across small sessions
- **Session size classification** (Top-up/Partial/Major)

## Key Features

### 1. Session Size Classification

Sessions are automatically classified based on SoC delta:
- **Top-up**: ΔSoC ≤ 20%
- **Partial**: 20% < ΔSoC ≤ 50%  
- **Major**: ΔSoC > 50%

### 2. Low Confidence Detection

Sessions are marked as low confidence if:
- `delta_miles < 15` OR
- `kwh_delivered < 3.0`

Low confidence sessions:
- Show efficiency chip in **muted** style
- Include explanatory tooltip
- Are excluded from weighted analytics (or weighted by their small kWh contribution)

### 3. Inline Chip Selection

The system automatically selects up to 3 chips per session row in priority order:

1. **Efficiency** — `X.Y mi/kWh`
   - Color bands: <2.0 red, 2.0–3.0 amber, >3.0 green
   - Muted if low confidence with tooltip explanation

2. **£/mi** — `Z.Zp/mi`
   - Grey if total cost == 0 (free charging)

3. **Petrol compare** — `✓ cheaper` or `✖ dearer`
   - Only shown if petrol baseline configured

4. **Fillers** (if slots available):
   - **Avg kW** (`avg_power_kw`)
   - **%/kWh** (percent per kWh)

### 4. kWh-Weighted Analytics

Dashboard and charts now use **kWh-weighted** calculations:

- **Efficiency**: `sum(efficiency × kWh) / sum(kWh)` for sessions with observed data
- **Cost per mile**: Derived from weighted efficiency
- **Excludes** low-confidence sessions from aggregates

This provides stable metrics that aren't dominated by small top-up sessions.

## Implementation Details

### Backend Changes

#### `services/derived_metrics.py`

New helper functions:
```python
def classify_session_size(delta_soc: float) -> str:
    # Returns "topup" | "partial" | "major"

def is_low_confidence(delta_miles: float, kwh: float) -> bool:
    # Returns True if session has small window
```

Updated `calculate_session_metrics()` to include:
- `delta_miles`: Miles since last anchor
- `size_bucket`: Session size classification
- `low_confidence`: Low confidence flag

Updated dashboard and chart methods to use kWh-weighted calculations.

### Frontend Changes

#### New Files
- `static/js/chip_selector.js`: Chip selection and rendering logic
- `static/css/style.css`: New chip styling classes

#### Updated Templates
- `charging_sessions/index.html`: Uses new chip selector
- `charging_sessions/_detail_drawer.html`: Shows session classification
- `dashboard/index.html`: Displays weighted efficiency
- `analytics/index.html`: Charts use weighted data

### CSS Classes

New utility classes for chips:
```css
.chip { /* base chip styling */ }
.chip--muted { opacity: .65; }
.chip--green { background-color: #198754; }
.chip--amber { background-color: #fd7e14; }
.chip--red { background-color: #dc3545; }
.chip--primary { background-color: #0d6efd; }
.chip--secondary { background-color: #6c757d; }
```

## Usage

### For Users

1. **Session List**: View up to 3 insight chips per session
2. **Details Drawer**: Click info button for full metrics + classification
3. **Dashboard**: See weighted efficiency in overview
4. **Analytics**: Charts show stable, weighted trends

### For Developers

1. **Adding new chip types**: Extend `selectInlineChips()` function
2. **Modifying thresholds**: Update constants in `is_low_confidence()`
3. **Custom styling**: Add new CSS classes following the pattern

## Testing

Run the test suite:
```bash
cd plugtrack
python test_session_chips.py
```

Tests cover:
- Session size classification
- Low confidence detection  
- Chip selection logic

## Configuration

### Low Confidence Thresholds
```python
# In derived_metrics.py
_ANCHOR_HORIZON_DAYS = 30  # Days to look back for anchor
# Low confidence thresholds are hardcoded:
# delta_miles < 15 or kwh < 3.0
```

### Session Size Buckets
```python
# Hardcoded in classify_session_size():
# TOPUP: ≤20%, PARTIAL: 21-50%, MAJOR: >50%
```

## Future Enhancements

1. **Settings Toggle**: User preference for kWh-weighted vs raw efficiency
2. **Custom Thresholds**: User-configurable low confidence thresholds
3. **Advanced Classification**: Machine learning for session patterns
4. **Export Options**: Include classification in CSV exports

## Troubleshooting

### Common Issues

1. **Chips not showing**: Check browser console for JavaScript errors
2. **Wrong efficiency**: Verify odometer data and anchor sessions
3. **Performance**: Large datasets may need pagination for chip loading

### Debug Mode

Enable debug logging in `derived_metrics.py`:
```python
_DEBUG_EFF = True  # Set to True for console logs
```

## API Changes

### New Metrics in Session Details

```json
{
  "metrics": {
    "delta_miles": 25.5,
    "size_bucket": "partial", 
    "low_confidence": false,
    // ... existing fields
  }
}
```

### Dashboard Response

```json
{
  "weighted_efficiency": 3.2,
  // ... existing fields
}
```

## Performance Considerations

- **Chip loading**: Async loading per session row
- **Weighted calculations**: Computed on-demand, cached in session
- **Database queries**: Optimized to avoid N+1 problems
- **Memory usage**: Minimal additional data per session

## Security

- All new endpoints require authentication
- User data isolation maintained
- No new database schema changes
- Input validation on all new parameters
