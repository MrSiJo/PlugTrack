# PlugTrack – Phase 2 Project Scope

## Overview
Phase 2 adds **analytics and insights** to PlugTrack. The goal is to turn raw charge session data into **useful metrics, trends, and visualisations** that help understand costs, efficiency, and usage patterns.  

All functionality builds on the Phase 1 schema — no destructive migrations should be needed.  

---

## Phase 2 Functional Scope

### 1. Analytics Dashboard
- Expand the **Dashboard** to include key calculated metrics:  
  - Average cost per kWh (over a time range)  
  - Average cost per mile  
  - Average efficiency (mi/kWh)  
  - Home vs public charging mix (% kWh, % cost)  
  - Total spend and kWh delivered (date range selectable)  

### 2. Charts & Trends
Use a charting library (e.g., Chart.js, Plotly, or similar).  

- **Cost per mile trend** over time.  
- **Energy delivered** (stacked by AC/DC).  
- **Efficiency (mi/kWh)** trend by date.  
- **Tariff history impact** (overlay cost per kWh with session data).  

Filters:  
- By car profile  
- By date range  
- By charge type (AC/DC/home/public)  

### 3. Data Filtering
- Session list and dashboard metrics must be filterable:  
  - By date range  
  - By location/network  
  - By car profile  
- Export filtered results as CSV.  

### 4. Derived Metrics (Backend Calculations)
For each charge session, calculate (not stored in DB, but derived on query):  
- **Total cost** = energy delivered × cost per kWh  
- **Miles gained** = energy delivered × efficiency (mi/kWh, from car profile)  
- **Cost per mile** = total cost ÷ miles gained  
- **% battery added** = SoC_to – SoC_from  

### 5. Recommended Charge Strategy (Phase 2 – Rules Engine)
Introduce simple **rule-based recommendations** (non-AI):  
- If SoC < recommended minimum (from car profile), suggest home charge.  
- If next 100% charge is overdue (based on `recommended_full_charge_frequency`), show reminder in top navigation dropdown.  
- If average home cost per kWh < public rate by a large margin → show "cheapest to charge at home" advice in top navigation dropdown.  

> **Note**: Recommendations are displayed in a notification-style dropdown in the top navigation bar, not directly on the dashboard. This provides persistent access to important charging advice across all pages.

---

## Database Updates
No new core tables. Instead:  
- Add a `derived_metrics.py` service layer to centralise calculations.  
- Add indexes for faster filtering:  
  ```sql
  CREATE INDEX idx_sessions_date ON charging_session(date);
  CREATE INDEX idx_sessions_car ON charging_session(car_id);
  CREATE INDEX idx_sessions_network ON charging_session(charge_network);
  ```

---

## UI Wireframes (Phase 2)

### Dashboard
```
---------------------------------------------------
Car: Cupra Born V2 (Active)
Battery: 59 kWh | Efficiency: 3.7 mi/kWh
---------------------------------------------------

[ Date Range Selector | Car Dropdown | Charge Type ]

Key Metrics (cards):
- Avg Cost per kWh: £0.21
- Avg Cost per Mile: 6.2p
- Avg Efficiency: 3.8 mi/kWh
- Home/Public Split: 72% / 28%
- Total Spend: £84.12 | Total kWh: 401

Charts:
[Cost per Mile Trend]   [Energy Delivered AC/DC]
[Efficiency Trend]      [Tariff History Impact]

> **Recommendations**: Available via lightbulb icon in top navigation bar
> - 100% charge overdue reminders
> - Home vs public charging cost advice
> - Battery health recommendations
```

### Sessions Page
- Add filter toolbar (date range, car, type, network).  
- Table updates live to reflect filters.  
- Add export button.  

---

## Code Structure Updates
```
/plugtrack
    /services
        derived_metrics.py   # backend calculations
        reports.py           # CSV exports
    /routes
        analytics.py         # new dashboard + charts
    /templates
        dashboard.html       # expanded with charts + metrics
        analytics/           # partials for charts
    /static
        /js/charts.js        # chart logic
```

---

## Implementation Notes for Cursor
1. Reuse Phase 1 schema — no migrations needed (except indexes).  
2. Add `derived_metrics.py` to encapsulate all calculations (cost/mi, kWh, efficiency).  
3. Use Chart.js (lightweight) for dashboard charts.  
4. Add filters (date range, car, type) to dashboard + sessions page.  
5. Add export to CSV for filtered sessions.  
6. Implement simple rules engine for recommendations (backend-driven).  
7. Extend Dashboard template to show metrics + charts per wireframe.  

---

## Deliverables for Phase 2
- Expanded dashboard with key metrics + charts.  
- Filters for sessions + dashboard.  
- CSV export for filtered sessions.  
- Rule-based recommendations (battery health + cost guidance).  
- Code structured to allow easy extension in Phase 3 (notifications + AI).  

---

✅ Phase 2 transforms PlugTrack from a logger into an **insight tool**, but avoids introducing AI or notifications yet.  
