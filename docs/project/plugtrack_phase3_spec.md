# PlugTrack – Phase 3 Plan (Session‑level Insights & Smart UX)

## Purpose
Turn PlugTrack from “log + charts” into a **coach**. Surface **per‑session insights** (mi/kWh, £/mile, %/kWh, taper hints), lightweight comparisons, and gentle guidance — without jumping straight to AI or notifications.

> Phase 3 builds on the P1 schema and P2 analytics. No destructive migrations required.

---

## What You’ll See (User Outcomes)
- Each charge row shows **quick insight chips**: `mi/kWh`, `£/mi`, `%/kWh`, and **“cheaper than petrol?”** marker.
- **Session detail drawer** with richer breakdown (cost components, estimated miles added, avg kW, taper band coverage).
- **Comparative context**: “vs last similar session” and “vs 30‑day average” deltas.
- **Smart hints**: “DC taper likely above 65% — consider stopping earlier” or “Home rate is 3× cheaper — finish at home.”
- **Blended suggestion button**: one‑click simulate “DC to X% + Home to Y%” from the selected session’s start SoC.

---

## Scope

### 1) Backend: Derived Metrics (session‑level)
Add a service (`services/derived_metrics.py`) exposing the following for **each session**:

- `total_cost = kWh * cost_per_kwh` (respect per‑session rate)
- `miles_gained = kWh * vehicle.efficiency_mpkwh`
- `cost_per_mile = total_cost / miles_gained` (handle divide‑by‑zero)
- `%_added = soc_to - soc_from`
- `% per kWh = %_added / kWh` (indicates effective usable capacity vs losses)
- `avg_power_kw = kWh / (duration_mins/60)` (when duration present)
- `dc_taper_flag` (heuristic: if type=DC and soc_to>65 or duration >> kWh/power)
- `petrol_threshold_ppm` (from settings: p/kWh threshold ÷ efficiency)
- `is_cheaper_than_petrol = (cost_per_mile * 100) <= petrol_threshold_ppm`

> Keep these **computed on the fly**. No new columns required. Consider a cached materialized view later if needed.

#### Similarity lookups (for deltas)
Helper that queries **recent sessions** with same `car_id` AND either:
- same `charge_type` and **within ±10% SoC window**, OR
- same **location/network**

Return: last similar session & rolling 30‑day averages.

---

### 2) UI: Session List Enhancements
- Add **insight chips** to each table row:
  - `mi/kWh` • `£/mi` • `%/kWh` • `avg kW`
  - Petrol badge: `✓ cheaper` or `× dearer`
- Use subtle colour:
  - Green for good value (bottom 25% £/mi), Amber middle, Red top 25%.
- Hover tooltip shows formula & values.

**Row actions**:
- **Details** (opens drawer on right or modal)
- **Blend** (prefill blended planner with `soc_from`, suggest DC cut‑off at 60–65%)

---

### 3) Session Detail Drawer (modal)
Sections:
- **Summary**: date, car, type, network, location.
- **Numbers**:
  - Energy (kWh), Total Cost (£), Cost/kWh, Cost/mi
  - SoC from→to, % added, %/kWh
  - Avg kW (and rated kW if set)
  - Miles gained (est) & efficiency used
- **Context**:
  - vs last similar: `£/mi Δ`, `avg kW Δ`, `%/kWh Δ`
  - vs 30‑day avg: same deltas
- **Hints** (if rules hit):
  - DC taper heuristics
  - “Finish at home” suggestion when home rate << public
  - “100% due” if car recommends monthly full charge and it’s overdue
- **Actions**: Edit, Duplicate, Simulate Blend

---

### 4) Blended Charge Mini‑Planner
Add a compact planner (side panel or modal) accessible from sessions + dashboard.

Inputs:
- Start SoC (pre‑filled from session.soc_from)
- **DC stop %** (default 60–65)
- **Home target %** (default car profile SoC max or 80)
- DC price (pre‑filled from session cost/kWh)
- Home price (from current home settings)

Outputs:
- DC time/cost (with simple taper model)
- Home time/cost
- **Total**: blended cost, blended £/mi
- Button: “Copy plan to notes” (appends to session notes) or “Log as new session” (optional P4/P5 idea)

> Taper model: piecewise power ratios (e.g., 10–50%:1.0, 50–70%:0.7, 70–80%:0.45). Keep configurable via settings later.

---

### 5) Rules / Hints (non‑AI)
Implement a tiny rules engine (`services/hints.py`) returning a list of strings (or code+message) per session.

Rules (examples):
- **DC taper**: if type=DC and soc_to > 65 → “Taper likely; consider stopping earlier.”
- **Finish at home**: if public £/kWh > 2× home rate and soc_to ≥ 60 → “Cheaper to finish at home.”
- **Low SoC storage**: if car parked >7 days and soc_to < 40 → “Consider topping to 50–60% for storage.”
- **100% due**: if car profile `recommended_full_charge_enabled` and `last_100%` older than threshold → “Full balance charge due.”

All hints are **dismissible** per session (store a tiny `ui_state` map in session notes JSON or a new `session_meta` table if you prefer cleanliness).

---

## Minimal Additions to Schema (optional but tidy)
No required migrations. If you want cleaner state management:

```sql
-- Optional for dismissed hint codes, saved blends, etc.
CREATE TABLE session_meta (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES charging_session(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  UNIQUE(session_id, key)
);

CREATE INDEX idx_session_meta_session ON session_meta(session_id);
```

---

## UI Wireframe Notes

### Sessions Table (row)
```
Date | Car | Type | SoC | kWh | £/kWh | £ Total | [ mi/kWh ] [ £/mi ] [ %/kWh ] [ avg kW ]  ✓ cheaper
                                        Details • Blend • Edit • Delete
```

### Detail Drawer
```
[Title] 2025‑08‑15 • Cupra Born • DC @ InstaVolt

Summary ...........
Key Numbers ......  (grid cards)
Comparative ....... (deltas vs similar & 30‑day)
Hints ............. (dismissible list)
Actions: [Edit] [Duplicate] [Simulate Blend]
```

### Blended Planner (compact)
```
Start SoC: 18%   DC stop: 65%   Home target: 80%
DC £/kWh: 0.68   Home £/kWh: 0.20

DC: 17.5 kWh • 0.5 h • £11.90
Home: 5.1 kWh • 2.2 h • £1.02
TOTAL: £12.92 • 9.7 p/mi    [Copy to notes] [Close]
```

---

## Code Structure Additions
```
/plugtrack
  /services
    derived_metrics.py   # extend with per‑session metrics + similarity
    hints.py             # tiny rule engine
    blend.py             # blended calc + taper helper
  /routes
    blend.py             # POST calculator endpoint
  /templates
    sessions/_chips.html         # reusable chips
    sessions/_detail_drawer.html # modal/drawer partial
    blend/_mini_planner.html
  /static/js
    session_drawer.js
```

---

## Implementation Checklist
- [ ] Extend `derived_metrics.py` with metrics + deltas
- [ ] Add chips to sessions table (server‑rendered partials)
- [ ] Implement detail drawer modal with metrics, comparisons, hints
- [ ] Add mini blended planner & endpoint
- [ ] Add `hints.py` rules; show dismissible hints
- [ ] (Optional) Add `session_meta` table for UI state (dismissed hints)
- [ ] Unit tests for metrics & hint rules

---

## Out‑of‑Scope (Phase 4/5)
- Notifications (Gotify/Apprise) → Phase 4/3.5
- AI narrative summaries → Phase 4/3.5
- Live charger APIs (Zap‑Map/OCM) → Phase 5
- PWA/Docker → Phase 4

---

## Success Criteria
- Sessions list displays **per‑session insight chips** without slowing the page.
- Detail drawer provides clear breakdown + comparisons in ≤1s.
- Mini blended planner outputs coherent cost/time with your tariffs.
- Hints are relevant, dismissible, and persist per session.

