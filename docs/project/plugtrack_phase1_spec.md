# PlugTrack – Phase 1 Project Scope

## Overview
PlugTrack is a personal web app for logging and managing **EV charging sessions** and **car profiles**.

- Built in **Python (Flask + SQLAlchemy ORM)**
- **SQLite** for persistence (migrations with Flask-Migrate)
- **Bootstrap 5** (or Tailwind) for responsive UI
- `.env` for environment-level config only (secret keys, DB path, debug flags)
- All **app/user settings stored in the database**, never in config files
- Sensitive values (API keys, passwords) **encrypted at rest**

The app must be **modular, extendable, and PWA-ready** in later phases.

---

## Phase 1 Functional Scope

### 1. User Management
- Single-user by default (future-proof schema for multi-user).
- Basic login/logout/register.
- Passwords stored as salted hash.
- Session-based authentication.

### 2. Car Profiles
- CRUD for cars.
- Fields:
  - Make
  - Model
  - Battery capacity (kWh)
  - Efficiency (mi/kWh, optional)
  - Active flag
  - Recommended 100% charge frequency (optional):
    - Enabled (boolean)
    - Frequency value (integer)
    - Frequency unit (enum: days, months)

### 3. Charging Sessions
- CRUD for charge sessions.
- Fields:
  - Date
  - Odometer
  - Charge type (AC/DC)
  - Charge speed (kW)
  - Location label
  - Charge network
  - Charge delivered (kWh)
  - Duration (minutes)
  - Cost per kWh
  - SoC from (%)
  - SoC to (%)
  - Notes (optional)
- Store **unit rate per session** → history is accurate if rates change later.

### 4. Settings
- Settings page with **tabs**:
  - **Cars** → Manage profiles
  - **Home Charging** → Manage tariff entries (p/kWh, valid_from, valid_to)
  - **Notifications** → Placeholder (Gotify/Apprise config)
  - **AI Integration** → Placeholder (OpenAI/Anthropic API key + prompts)
- All stored in `settings` table, encrypted if sensitive.

### 5. Dashboard
- Show active car summary (Make, Model, Battery size, Efficiency).
- Show **last 5 charging sessions**.
- Placeholder section for quick stats (e.g., cost/mi, efficiency).

---

## Database ERD

```mermaid
erDiagram
    USER {
        int id PK
        string username
        string password_hash
        datetime created_at
    }

    CAR {
        int id PK
        int user_id FK
        string make
        string model
        float battery_kwh
        float efficiency_mpkwh
        boolean active
        boolean recommended_full_charge_enabled
        int recommended_full_charge_frequency_value
        string recommended_full_charge_frequency_unit // enum: 'days','months'
    }

    CHARGING_SESSION {
        int id PK
        int user_id FK
        int car_id FK
        date date
        int odometer
        string charge_type // AC/DC
        float charge_speed_kw
        string location_label
        string charge_network
        float charge_delivered_kwh
        int duration_mins
        float cost_per_kwh
        int soc_from
        int soc_to
        string notes
        datetime created_at
    }

    SETTINGS {
        int id PK
        int user_id FK
        string key
        string value
        boolean encrypted
    }

    USER ||--o{ CAR : owns
    USER ||--o{ CHARGING_SESSION : logs
    CAR ||--o{ CHARGING_SESSION : "related to"
    USER ||--o{ SETTINGS : configures
```

---

## UI Wireframes (Spec)

### Navigation
```
[ Dashboard ] [ Charging Sessions ] [ Settings ] [ Logout ]
```

### Dashboard
- Active car summary (Make, Model, Battery, Efficiency).
- Table of recent 5 sessions:
  - Date | Type | SoC from→to | kWh delivered | Cost per kWh | Location | Notes
- Placeholder section for future quick stats (efficiency, cost trends).

### Charging Sessions
- Table of all sessions (sortable + filterable).
- Add/Edit/Delete options.
- Export to CSV.
- Add Session Form with all session fields.

### Settings (Tabbed UI)
- **Cars**
  - Table: Make, Model, Battery, Efficiency, Recommended 100% Frequency.
  - Add/Edit/Delete form.
- **Home Charging**
  - Table: Tariffs (p/kWh, valid from, valid to).
  - Add/Edit/Delete form.
- **Notifications** (placeholder).
- **AI Integration** (placeholder).

---

## Code Structure

```
/plugtrack
    /models
        __init__.py
        user.py
        car.py
        charging_session.py
        settings.py
    /routes
        __init__.py
        auth.py
        cars.py
        charging_sessions.py
        settings.py
        dashboard.py
    /services
        __init__.py
        encryption.py
        forms.py
    /templates
        base.html
        dashboard.html
        cars/
        charging_sessions/
        settings/
        auth/
    /static
        /css
        /js
.env
config.py
run.py
```

---

## Implementation Notes for Cursor
1. Scaffold project with the above structure.
2. Implement SQLite schema with SQLAlchemy models per ERD.
3. Add migrations support (Flask-Migrate).
4. Implement CRUD routes + templates for Cars, Charging Sessions, Settings.
5. Implement Dashboard route + template showing summary + last 5 sessions.
6. Use Bootstrap 5 for responsive tables/forms/navigation.
7. `.env` should configure app secret key + DB path only.
8. Sensitive settings stored encrypted using `cryptography.fernet`.
9. Seed with one demo car + sample session.

---

## Deliverables for Phase 1
- A working Flask app with modular blueprints.
- SQLite DB with schema from ERD.
- CRUD functionality for Cars, Charging Sessions, and Home Charging Rates.
- Dashboard showing car + last 5 sessions.
- Settings page with tabs and placeholders for Notifications + AI.
- Encryption service for sensitive DB fields.
