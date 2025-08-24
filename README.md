# PlugTrack

PlugTrack is a personal web app for logging and managing **EV charging sessions** and **car profiles**.  
It is designed to be modular, extendable, and future-proof, with support for analytics, notifications, AI insights, and live charger data planned in later phases.

---

## 🚗 Project Goals
- Track charging sessions with accurate cost-per-session history.
- Manage car profiles, including battery size, efficiency, and recommended charging habits.
- Provide insights into cost per mile, charging efficiency, and battery health (future phases).
- Offer flexible configuration entirely through the app UI (not config files).
- Support notifications and AI-driven insights in later phases.
- Deployable as a PWA and containerised app in later phases.

---

## 📦 Tech Stack
- **Backend**: Python (Flask + SQLAlchemy ORM)
- **Database**: SQLite (migrations with Flask-Migrate)
- **Frontend**: Jinja2 templates with Bootstrap 5 (responsive UI)
- **Config**: `.env` for environment-level settings only
- **Security**: Sensitive data (API keys, passwords) encrypted before storage

---

## 🔖 Project Roadmap

### Phase 1 – Core Foundations ✅ (Current)
- Modular Flask app with blueprints
- User authentication (single-user support initially)
- Car profiles with recommended charging frequency
- Charging session CRUD (with historical tariff accuracy)
- Settings page with tabs for Cars, Home Charging, Notifications*, AI Integration*
- Dashboard with active car summary + recent sessions
- Encryption support for sensitive settings

### Phase 2 – Analytics & Insights
- Charts and trends (cost per mile, kWh efficiency, charging mix)
- Filterable dashboards
- Rule-based recommendations

### Phase 3 – Notifications & AI
- Gotify/Apprise notifications (charge reminders, alerts)
- AI integration (OpenAI/Anthropic) for narrative summaries and insights

### Phase 4 – PWA & Docker
- PWA support (offline mode, mobile installable)
- Docker containerisation for easy deployment

### Phase 5 – Live Charger Data
- Integration with public charger APIs (Zap-Map or similar)
- Real-time price/availability checks
- Optimised blended charging recommendations

---

## 📂 Documentation
Detailed specifications for each phase are in the `/docs` directory.  
- [Phase 1 Specification](./plugtrack_phase1_spec.md)

---

## ⚡ Getting Started

### Prerequisites
- Python 3.11+
- pip + virtualenv

### Setup
```bash
git clone <repo-url>
cd plugtrack
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask db upgrade
flask run
```

---

## 📝 License
This project is for **personal use**, but is intended to remain open source and adaptable for others.
