# PlugTrack Phase 3 Implementation Guide

## Overview

Phase 3 transforms PlugTrack from a simple "log + charts" application into a **smart charging coach** that provides session-level insights, smart hints, and blended charging strategies.

## New Features

### 1. Session-Level Insight Chips
Each charging session now displays:
- **mi/kWh**: Miles gained per kWh (efficiency)
- **£/mi**: Cost per mile with color coding (green=good, amber=middle, red=expensive)
- **%/kWh**: Battery percentage added per kWh
- **avg kW**: Average charging power
- **Petrol comparison**: ✓ cheaper or × dearer than petrol threshold

### 2. Smart Hints Engine
Automated recommendations including:
- **DC Taper Warnings**: Suggests stopping DC charging earlier to avoid slow taper
- **Finish at Home**: Recommends completing charging at home when public rates are expensive
- **Storage SoC**: Advises on optimal battery levels for long-term storage
- **100% Charge Due**: Reminds when balance charging is needed

### 3. Blended Charge Planner
Simulates optimal DC + Home charging strategies:
- Calculates optimal DC stop point based on cost comparison
- Models DC taper effects using configurable power bands
- Estimates total cost and time for blended approach
- Saves plans to session notes

### 4. Session Detail Drawer
Comprehensive session analysis including:
- Detailed metrics breakdown
- Comparison with similar sessions
- 30-day rolling averages
- Dismissible smart hints

## Installation & Setup

### 1. Run Database Migrations
```bash
cd PlugTrack/plugtrack
python migrate_phase3.py
```

### 2. Seed Default Settings
```bash
python seed_phase3_settings.py
```

### 3. Restart the Application
```bash
python run_app.py
```

## Configuration

### Default Settings (automatically seeded)
- **petrol_threshold_p_per_kwh**: 52.5 (p/kWh threshold for petrol comparison)
- **default_efficiency_mpkwh**: 3.7 (fallback efficiency if car profile missing)
- **home_aliases_csv**: "home,house,garage" (location keywords for home detection)

### DC Taper Model
Default power bands (configurable in future):
- 10-50%: 100% power
- 50-70%: 70% power  
- 70-80%: 45% power

## Usage

### Viewing Session Insights
1. Navigate to **Charging Sessions**
2. Each session row now shows insight chips
3. Hover over chips for detailed tooltips
4. Click **Details** button for comprehensive analysis

### Using the Blended Planner
1. Click **Simulate Blend** button on any session
2. Adjust SoC targets and rates as needed
3. Click **Calculate Blend** to see results
4. **Copy to Notes** to save the plan

### Managing Hints
1. View hints in the session detail drawer
2. Click **×** to dismiss hints you don't want to see again
3. Hints are automatically generated based on session data

## Technical Implementation

### New Database Tables
- **session_meta**: Stores dismissed hints, saved blends, and UI state
- **venue_type**: Optional field in charging_session for explicit home/public classification

### New Services
- **DerivedMetricsService**: Enhanced with session-level calculations
- **HintsService**: Rules engine for smart recommendations
- **BlendedChargeService**: DC taper modeling and cost optimization

### New Routes
- **/blend/plan**: Calculate blended charging strategies
- **/blend/suggest**: Get optimal DC stop recommendations
- **/blend/save**: Save blend plans to session notes
- **/charging-sessions/{id}/details**: Get comprehensive session data
- **/charging-sessions/{id}/dismiss-hint**: Dismiss smart hints

### Frontend Enhancements
- Insight chips with color-coded badges
- Modal-based session detail drawer
- Blended charge planner interface
- Responsive design with Bootstrap 5

## API Endpoints

### Blended Charge Planning
```http
POST /blend/plan
{
  "start_soc": 20,
  "dc_stop_soc": 65,
  "home_target_soc": 80,
  "dc_power_kw": 50.0,
  "dc_cost_per_kwh": 0.68,
  "home_cost_per_kwh": 0.20,
  "car_id": 1
}
```

### Session Details
```http
GET /charging-sessions/{id}/details
```

### Dismiss Hint
```http
POST /charging-sessions/{id}/dismiss-hint
{
  "hint_code": "dc_taper"
}
```

## Customization

### Adding New Hint Types
1. Extend `HintsService` with new hint methods
2. Add hint templates to the UI
3. Update the hints rendering logic

### Modifying DC Taper Model
1. Edit `DEFAULT_TAPER_BANDS` in `BlendedChargeService`
2. Add per-vehicle override capability
3. Create UI for user configuration

### New Metrics
1. Add calculations to `DerivedMetricsService.calculate_session_metrics()`
2. Update the insight chips template
3. Include in session detail drawer

## Troubleshooting

### Common Issues

**Insight chips not loading:**
- Check browser console for JavaScript errors
- Verify `/charging-sessions/{id}/details` endpoint is working
- Ensure database migrations completed successfully

**Blended planner errors:**
- Verify car efficiency values are set
- Check that SoC values are valid (0-100)
- Ensure DC power and cost values are positive

**Hints not appearing:**
- Check if hints are dismissed in session_meta table
- Verify car profile settings (e.g., recommended_full_charge_enabled)
- Check location detection for home vs public charging

### Debug Mode
Enable debug logging in Flask to see detailed request/response information:
```python
app.config['DEBUG'] = True
```

## Future Enhancements (Phase 4/5)

- **AI-powered insights**: Machine learning for personalized recommendations
- **Live charger data**: Integration with Zap-Map/OCM APIs
- **Notifications**: Gotify/Apprise integration for smart alerts
- **Advanced analytics**: Predictive charging cost modeling
- **Mobile app**: Progressive Web App (PWA) capabilities

## Support

For issues or questions about Phase 3:
1. Check the browser console for JavaScript errors
2. Review Flask application logs
3. Verify database schema matches expected structure
4. Test individual API endpoints for functionality

## Performance Notes

- Insight chips are loaded asynchronously to avoid blocking page load
- Session details are fetched on-demand to reduce initial page size
- Blended calculations use efficient algorithms for real-time response
- Database queries are optimized with proper indexing
