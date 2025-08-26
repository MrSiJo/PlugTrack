# PlugTrack - Phase 5 Specification
Insight Polish, Confidence UX, and Reminders

---

## 5.1 Insight Upgrades (data already available)
**Goal:** Add higher-signal insights without new APIs.

### Deliverables
- **New chips/metrics**
  - **£/10% SOC** (`total_cost / ((ΔSOC)/10)`; guards for ΔSOC=0)
  - **Home ROI delta (p/mi)** vs 30-day *home* baseline (exclude free sessions)
  - **Loss estimate (%)** in Details (`expected_soc_from_kwh – observed ΔSOC`, using car `battery_kwh`)
- **Battery hygiene widget** on Dashboard
  - Time distribution in SoC bands: `<30%`, `30–80%`, `>80%` (last 30/90 days)
  - “Last 100%” date + “Due by” date (uses car’s recommended 100% rule)
- **Location leaderboard**
  - Per location: median **£/kWh**, median **£/mi**, typical start/stop SoC, session count

### DB / Services
- No schema change (you already have fields).
- Add `services/insights.py` with helpers.

### UI
- Session list: swap one filler chip for **£/10%** or **Home ROI delta**.
- Details drawer: show **Loss %**, and “Battery hygiene” footer.

---

## 5.2 Confidence UX & Explainability
**Goal:** Make “why low confidence?” obvious and helpful.

### Deliverables
- **Confidence reasons** surfaced:
  - `small_window (kWh < 3.0 or Δmi < 15)`
  - `stale_anchors (>10 days)`
  - `outlier_clamped (mi/kWh < 1 or > 7)`
- **Badges + tooltips** on chips and in Details.
- **“Confidence guide” modal** (explains thresholds).
- **Settings → Advanced**: expose thresholds (min Δmi, min kWh, anchor horizon days, clamp range).

### DB / Services
- Return `confidence_reasons: list[str]` alongside `efficiency_confidence`.

### UI
- Chips: dot colour + tooltip shows reason.
- Details: “Confidence” row lists reasons.

---

## 5.3 Ambient Temp & Pre-conditioning Capture
**Goal:** Capture extra fields to sharpen context.

### Deliverables
- **Charging session form**: fields
  - `ambient_temp_c` (already present; surface in form & details)
  - `preconditioning_used` (Yes/No/Unknown)
  - `preconditioning_events` (integer, optional)
- **Analytics usage**:
  - Badge in details if preconditioning flagged.
  - Filter “exclude preconditioning sessions” in Analytics.

### DB
- Add columns to `charging_session`:
  - `preconditioning_used` (nullable boolean)
  - `preconditioning_events` (nullable int)

---

## 5.4 Monthly 100% Charge Reminder
**Goal:** Honour manufacturer guidance with reminders.

### Deliverables
- **Reminder engine** (`services/reminders.py`):
  - `check_full_charge_due(user_id, car_id)`
- **Daily check**:
  - **CLI**: `flask reminders-run`
  - Optional APScheduler in-app daily @09:00
- **In-app notifications**:
  - Navbar bell + Dashboard card if overdue.

### DB
- No schema change; reuse car profile settings.

---

## 5.5 Settings tidy & small docs
**Deliverables**
- Settings page grouping:
  - Car Profile: “Recommended 100% frequency” clarified
  - Advanced: thresholds for confidence
- “What affects confidence?” help link in Details & Settings

---

## Suggested Order
1. **5.1 Insight Upgrades**
2. **5.2 Confidence UX**
3. **5.4 Reminders**
4. **5.3 Ambient/Pre-conditioning**
5. **5.5 Settings tidy & docs**
