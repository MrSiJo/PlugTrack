# PlugTrack - EV Charging Session Manager

PlugTrack is a personal web application for logging and managing EV charging sessions and car profiles. Built with Python Flask, it provides a comprehensive solution for tracking your electric vehicle charging habits, costs, and efficiency. **PlugTrack has evolved from a simple logger into a smart charging coach that provides insights, analytics, and recommendations.**

## Features

### Phase 1: Foundation ✅ Complete
- **User Management**: Secure authentication with password hashing
- **Car Profiles**: Manage multiple vehicles with battery capacity, efficiency tracking, and recommended 100% charge frequency
- **Charging Sessions**: Log detailed charging sessions with cost tracking, SoC monitoring, and location management
- **Dashboard**: Overview of active car and recent charging sessions
- **Settings**: Configurable home charging rates and placeholders for future features
- **Data Export**: CSV export functionality for charging sessions

### Phase 2: Analytics & Insights ✅ Complete
- **Analytics Dashboard**: Comprehensive metrics and trends with interactive charts
- **Key Metrics**: Average cost per kWh, cost per mile, efficiency, home vs public charging mix
- **Charts & Trends**: 
  - Cost per mile trend over time
  - Energy delivered (AC/DC split)
  - Efficiency (mi/kWh) trend with realistic variations
  - Home vs public charging distribution
- **Data Filtering**: Filter by date range, car profile, charge type, and network
- **Performance Optimization**: Database indexes for fast filtering and queries
- **Smart Recommendations**: Rule-based charging advice accessible via top navigation

### Phase 3: Smart Coaching ✅ Complete
- **Session-Level Insights**: Each charging session displays efficiency chips, cost analysis, and petrol comparison
- **Smart Hints Engine**: Automated recommendations including:
  - DC taper warnings (suggest stopping earlier to avoid slow charging)
  - "Finish at home" suggestions when public rates are expensive
  - Storage SoC advice for long-term parking
  - 100% balance charge reminders
- **Blended Charge Planner**: Simulate optimal DC + Home charging strategies with:
  - DC taper modeling using configurable power bands
  - Cost optimization between public and home charging
  - Time and cost estimates for blended approaches
- **Session Detail Drawer**: Comprehensive analysis with comparisons, hints, and actions
- **Comparative Analysis**: Compare sessions with similar conditions and 30-day rolling averages

### Phase 4: Data Ops & Settings ✅ Complete
- **CLI Import/Export**: CSV import/export with validation and duplicate detection
- **Backup/Restore**: ZIP backup/restore with merge/replace modes and auto-backup safety
- **Settings Management**: Seeded defaults for all Phase 4 settings with framework-agnostic services
- **Database Performance**: New indexes for pagination, odometer scans, and duplicate detection
- **Development Infrastructure**: Docker dev setup and comprehensive testing suite
- **Future-Ready Architecture**: Services designed for UI integration with zero refactor

## Technology Stack

- **Backend**: Python 3.11+, Flask 3.0
- **Database**: SQLite with SQLAlchemy ORM, optimized with performance indexes
- **Frontend**: Bootstrap 5, HTML5, CSS3, JavaScript with Chart.js for analytics
- **Authentication**: Flask-Login with secure password hashing
- **Security**: Encryption service for sensitive data
- **Migrations**: Flask-Migrate for database schema management
- **Charts**: Chart.js for interactive data visualization
- **CLI**: Click framework for command-line operations

## Security

### Demo Credentials
This repository includes demo credentials for first-time setup:
- **Username**: `demo`
- **Password**: `demo123`

⚠️ **IMPORTANT**: These are demo credentials only and should NEVER be used in production!

### Production Security
For production deployment, you MUST:

1. **Set SECRET_KEY**: Generate a secure random key
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Set ENCRYPTION_KEY**: Generate a Fernet encryption key
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. **Change Demo Password**: Use the admin creation command to set a secure password
   ```bash
   flask create-admin
   ```

4. **Environment Variables**: Ensure all sensitive values are set in your `.env` file

### Security Features
- **Password Hashing**: Secure password storage using Werkzeug's security functions
- **Session Management**: Flask-Login with secure session handling
- **Data Encryption**: Sensitive data encrypted using Fernet encryption
- **CSRF Protection**: Built-in CSRF protection for forms
- **SQL Injection Protection**: SQLAlchemy ORM prevents SQL injection attacks

## Installation

### Prerequisites
- Python 3.11 or higher
- pip (Python package installer)

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd PlugTrack/plugtrack
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   
   # On Windows
   venv\Scripts\activate
   
   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   # Copy the example environment file
   cp env_example.txt .env
   
   # Edit .env with your configuration
   # Generate a secret key and encryption key
   ```

5. **Generate encryption key**
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

6. **Initialize the database**
   ```bash
   flask --app . init-db
   ```

7. **Run database migrations (if needed)**
   ```bash
   python migrations/add_phase4_fields_and_indexes.py
   python migrations/seed_phase4_settings.py
   ```

8. **Run the application**
   ```bash
   python run.py
   ```

## Usage

### Default Login
After running `flask --app . init-db`, you can log in with:
- **Username**: `demo`
- **Password**: `demo123`

### Key Features

#### Smart Recommendations
- **Top Navigation**: Click the lightbulb icon to view charging recommendations
- **Real-time Updates**: Recommendations update based on your charging patterns
- **Dismissible Hints**: Dismiss hints you don't want to see again

#### Analytics Dashboard
- **Interactive Charts**: Hover over charts for detailed information
- **Filtering**: Use date ranges and car filters to analyze specific periods
- **Export**: Download filtered data as CSV for external analysis

#### Blended Charge Planning
- **Session Integration**: Click "Simulate Blend" on any charging session
- **Cost Optimization**: Compare DC vs home charging costs
- **Realistic Modeling**: DC taper effects and time calculations

#### CLI Operations (Phase 4)
- **Export Sessions**: `flask --app . sessions-export --to sessions.csv`
- **Import Sessions**: `flask --app . sessions-import --from sessions.csv --dry-run`
- **Create Backup**: `flask --app . backup-create --to backup.zip`
- **Restore Backup**: `flask --app . backup-restore --from backup.zip --mode merge`

### Creating a New User
```bash
flask --app . create-admin
```

### Database Management
```bash
# Create a new migration
flask db migrate -m "Description of changes"

# Apply migrations
flask db upgrade

# Rollback migrations
flask db downgrade
```

## Project Structure

```
plugtrack/
├── models/                 # Database models
│   ├── __init__.py
│   ├── user.py            # User authentication
│   ├── car.py             # Car profiles
│   ├── charging_session.py # Charging sessions
│   ├── settings.py        # User settings
│   └── session_meta.py    # Session metadata and hints
├── routes/                 # Flask routes/views
│   ├── __init__.py
│   ├── auth.py            # Authentication routes
│   ├── cars.py            # Car management
│   ├── charging_sessions.py # Session management
│   ├── settings.py        # Settings management
│   ├── dashboard.py       # Dashboard view
│   ├── analytics.py       # Analytics dashboard
│   └── blend.py           # Blended charging planner
├── services/               # Business logic
│   ├── __init__.py
│   ├── encryption.py      # Data encryption
│   ├── forms.py           # Form definitions
│   ├── derived_metrics.py # Analytics calculations
│   ├── hints.py           # Smart hints engine
│   ├── blend.py           # Blended charging logic
│   ├── reports.py         # CSV export functionality
│   ├── validators.py      # Validation and report types (Phase 4)
│   ├── io_sessions.py     # CSV import/export service (Phase 4)
│   ├── io_backup.py       # Backup/restore service (Phase 4)
│   └── baseline_manager.py # Baseline session management
├── templates/              # HTML templates
│   ├── base.html          # Base template with navigation
│   ├── auth/              # Authentication templates
│   ├── cars/              # Car management templates
│   ├── charging_sessions/ # Session templates with insights
│   ├── settings/          # Settings templates
│   ├── dashboard/         # Dashboard templates
│   └── analytics/         # Analytics dashboard templates
├── static/                 # Static assets
│   ├── css/               # Stylesheets
│   └── js/                # JavaScript for interactivity
├── migrations/             # Database migration scripts
│   ├── add_phase4_fields_and_indexes.py
│   └── seed_phase4_settings.py
├── config.py               # Configuration
├── run.py                  # Application entry point
├── requirements.txt        # Python dependencies
├── test_phase4.py         # Phase 4 test suite
├── Dockerfile.dev          # Development Docker setup
└── docker-compose.dev.yml  # Development Docker Compose
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask secret key | `dev-secret-key-change-in-production` |
| `FLASK_DEBUG` | Enable debug mode | `False` |
| `DATABASE_URL` | Database connection string | `sqlite:///plugtrack.db` |
| `ENCRYPTION_KEY` | Encryption key for sensitive data | Required |

### Default Settings (Automatically Seeded)
- **petrol_threshold_p_per_kwh**: 52.5 (p/kWh threshold for petrol comparison)
- **default_efficiency_mpkwh**: 4.1 (fallback efficiency if car profile missing)
- **home_aliases_csv**: "home,house,garage" (location keywords for home detection)
- **home_charging_speed_kw**: 2.3 (default home charging speed)
- **petrol_price_p_per_litre**: 128.9 (current petrol price)
- **petrol_mpg**: 60.0 (petrol efficiency for comparisons)
- **allow_efficiency_fallback**: 1 (enable efficiency fallback logic)

### DC Taper Model
Default power bands for realistic charging simulation:
- 10-50%: 100% power
- 50-70%: 70% power  
- 70-80%: 45% power

## Security Features

- **Password Hashing**: Secure password storage using Werkzeug's security functions
- **Session Management**: Flask-Login for secure user sessions
- **Data Encryption**: Sensitive settings encrypted at rest using Fernet
- **CSRF Protection**: Built-in CSRF protection with Flask-WTF
- **Input Validation**: Comprehensive form validation and sanitization

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Roadmap

### Phase 4 ✅ Complete
- **CLI Import/Export**: CSV import/export with validation and duplicate detection
- **Backup/Restore**: ZIP backup/restore with merge/replace modes
- **Settings Management**: Seeded defaults and framework-agnostic services
- **Database Performance**: New indexes and optimizations
- **Development Infrastructure**: Docker setup and testing suite

### Phase 5 (Future)
- **AI Integration**: OpenAI/Anthropic API for narrative insights
- **Notifications**: Gotify/Apprise integration for smart alerts
- **Live Charger Data**: Integration with Zap-Map/OCM APIs
- **PWA Support**: Progressive Web App capabilities
- **Advanced Analytics**: Predictive charging cost modeling

### Phase 6 (Future)
- **Multi-user Support**: Team and family charging management
- **Mobile App**: Native mobile applications
- **Charging Network Integration**: Real-time availability and pricing
- **Weather Integration**: Temperature-based efficiency adjustments

## Support

For support and questions, please open an issue on the GitHub repository.

## Acknowledgments

- Flask community for the excellent web framework
- Bootstrap team for the responsive UI framework
- SQLAlchemy team for the powerful ORM
- Chart.js team for the interactive charting library
- Click team for the CLI framework
