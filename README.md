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
- **Charts**: Chart.js for interactive visualizations
- **Config**: `.env` for environment-level settings only
- **Security**: Sensitive data (API keys, passwords) encrypted before storage

---

## 🔖 Project Roadmap

### Phase 1 – Core Foundations ✅ (Completed)
- Modular Flask app with blueprints
- User authentication (single-user support initially)
- Car profiles with recommended charging frequency
- Charging session CRUD (with historical tariff accuracy)
- Settings page with tabs for Cars, Home Charging, Notifications*, AI Integration*
- Dashboard with active car summary + recent sessions
- Encryption support for sensitive settings

### Phase 2 – Analytics & Insights ✅ (Current)
- **Analytics Dashboard** with comprehensive metrics and charts
- **Cost per mile trends** and efficiency analysis
- **Home vs Public charging** mix analysis
- **Filterable dashboards** by date range, car, and charge type
- **Rule-based recommendations** for battery health and cost optimization
- **Enhanced CSV exports** with derived metrics
- **Performance optimizations** with database indexes

### Phase 3 – Notifications & AI (Planned)
- Gotify/Apprise notifications (charge reminders, alerts)
- AI integration (OpenAI/Anthropic) for narrative summaries and insights

### Phase 4 – PWA & Docker (Planned)
- PWA support (offline mode, mobile installable)
- Docker containerisation for easy deployment

### Phase 5 – Live Charger Data (Planned)
- Integration with public charger APIs (Zap-Map or similar)
- Real-time price/availability checks
- Optimised blended charging recommendations

---

## 📂 Documentation
Detailed specifications for each phase are in the project directory.  
- [Phase 1 Specification](./plugtrack_phase1_spec.md)
- [Phase 2 Specification](./plugtrack_phase2_spec.md)

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
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask db upgrade
python add_phase2_indexes.py  # Add performance indexes
flask run
```

### Phase 2 Features
After setup, you'll have access to:

1. **Enhanced Dashboard** - Filterable metrics with date range and car selection
2. **Analytics Page** - Interactive charts showing cost trends, efficiency, and charging patterns
3. **Smart Recommendations** - Rule-based suggestions for optimal charging
4. **Advanced Filtering** - Filter sessions by date, car, type, and network
5. **Enhanced Exports** - CSV exports with calculated metrics like cost per mile

### Key Metrics Available
- **Cost Analysis**: Average cost per kWh, cost per mile, total spend
- **Efficiency**: Miles gained, efficiency trends over time
- **Charging Patterns**: Home vs public split, AC vs DC usage
- **Battery Health**: 100% charge reminders, optimal charging frequency

---

## 📝 License
This project is for **personal use**, but is intended to remain open source and adaptable for others.
