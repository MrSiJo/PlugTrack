![logo](docs/assets/plugtrack_banner.png)
# PlugTrack - EV Charging Session Manager

PlugTrack is a smart personal web application for logging and managing EV charging sessions and car profiles. Built with Python Flask, it provides comprehensive tracking of your electric vehicle charging habits, costs, and efficiency with intelligent insights and recommendations.

## Features

### Smart Charging Management
- **Car Profiles**: Manage multiple vehicles with battery capacity, efficiency tracking, and recommended 100% charge frequency
- **Charging Sessions**: Log detailed charging sessions with cost tracking, SoC monitoring, and location management
- **Smart Recommendations**: Automated charging advice based on your patterns and preferences
- **Session Insights**: Each charging session displays efficiency chips, cost analysis, and petrol comparison

### Analytics & Insights
- **Comprehensive Dashboard**: Overview of active car and recent charging sessions
- **Analytics Dashboard**: Interactive charts showing cost trends, efficiency, and charging mix
- **Key Metrics**: Average cost per kWh, cost per mile, efficiency, home vs public charging distribution
- **Data Filtering**: Filter by date range, car profile, charge type, and network

### Smart Coaching Features
- **Blended Charge Planner**: Simulate optimal DC + Home charging strategies with cost optimization
- **Real-time Hints**: DC taper warnings, "finish at home" suggestions, storage SoC advice
- **Comparative Analysis**: Compare sessions with similar conditions and rolling averages
- **Session Detail Analysis**: Comprehensive breakdowns with actionable recommendations

### Data Management
- **User Management**: Secure authentication with password hashing
- **Settings Management**: Configurable charging rates, preferences, and defaults
- **Data Export**: CSV export functionality for charging sessions
- **CLI Operations**: Import/export sessions and backup/restore functionality
- **Backup System**: ZIP-based backup and restore with merge/replace modes

## Screenshots


**Dashboard Overview** - Main dashboard showing current car and recent sessions
![dashboard](docs/assets/Dashboard_PlugTrack.png)
**Analytics Dashboard** - Interactive charts and metrics for charging analysis
![analytics](docs/assets/Analytics_PlugTrack.png)
**Charging Sessions** - Charging Session page
![chargingsessions](docs/assets/ChargingSessions_PlugTrack.png)
**Session Detail** - Detailed view of a charging session with insights and recommendations
![chargingsessionsdetail](docs/assets/ChargingSessionDetail_PlugTrack.png)
**Blended Charge Planner** - DC + Home charging simulation interface
![blendedcharge](docs/assets/BlendedChargePlanner_PlugTrack.png)
**Car Management** - Add and manage multiple vehicle profiles
![cars](docs/assets/Cars_PlugTrack.png)
**Settings Panel** - Configure charging rates and preferences
![settings](docs/assets/Settings_PlugTrack.png)

## Technology Stack

- **Backend**: Python 3.11+, Flask 3.0
- **Database**: SQLite with SQLAlchemy ORM, optimized with performance indexes
- **Frontend**: Bootstrap 5, HTML5, CSS3, JavaScript with Chart.js for analytics
- **Authentication**: Flask-Login with secure password hashing
- **Security**: Encryption service for sensitive data
- **Migrations**: Flask-Migrate for database schema management
- **Charts**: Chart.js for interactive data visualization
- **CLI**: Click framework for command-line operations

## Quick Start

### Prerequisites
- Python 3.11 or higher
- pip (Python package installer)

### Installation

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
   # Generate required keys (see Security section below)
   ```

5. **Generate required keys**
   ```bash
   # Generate secret key
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   
   # Generate encryption key
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

6. **Initialize the database**
   ```bash
   flask --app . init-db
   ```

7. **Run database migrations**
   ```bash
   python migrations/add_phase4_fields_and_indexes.py
   python migrations/seed_phase4_settings.py
   ```

8. **Run the application**
   ```bash
   python run.py
   ```

9. **Access the application**
   - Open your browser to `http://localhost:5000`
   - Login with demo credentials: `demo` / `demo123`

## Security

### Demo Credentials
This repository includes demo credentials for first-time setup:
- **Username**: `demo`
- **Password**: `demo123`

⚠️ **IMPORTANT**: These are demo credentials only and should NEVER be used in production!

### Production Security
For production deployment, you MUST update these security settings:

1. **Set SECRET_KEY**: Generate a secure random key
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Set ENCRYPTION_KEY**: Generate a Fernet encryption key
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. **Change Demo Password**: Use the admin creation command
   ```bash
   flask create-admin
   ```

### Security Features
- **Password Hashing**: Secure password storage using Werkzeug's security functions
- **Session Management**: Flask-Login with secure session handling
- **Data Encryption**: Sensitive data encrypted using Fernet encryption
- **CSRF Protection**: Built-in CSRF protection for forms
- **SQL Injection Protection**: SQLAlchemy ORM prevents SQL injection attacks

## Usage Guide

### Getting Started
1. **Login**: Use the demo credentials or create a new admin user
2. **Add a Car**: Create your first car profile with battery capacity and efficiency
3. **Configure Settings**: Set your home charging rate and other preferences
4. **Log Sessions**: Start recording your charging sessions
5. **View Analytics**: Explore the analytics dashboard for insights

### Key Features

#### Smart Recommendations
- Click the lightbulb icon in the top navigation to view charging recommendations
- Recommendations update based on your charging patterns
- Dismiss hints you don't want to see again

#### Analytics Dashboard
- Hover over charts for detailed information
- Use date ranges and car filters to analyze specific periods
- Download filtered data as CSV for external analysis

#### Blended Charge Planning
- Click "Simulate Blend" on any charging session
- Compare DC vs home charging costs
- Get realistic time and cost estimates for optimal charging strategies

#### CLI Operations
```bash
# Export sessions
flask --app . sessions-export --to sessions.csv

# Import sessions (dry run first)
flask --app . sessions-import --from sessions.csv --dry-run

# Create backup
flask --app . backup-create --to backup.zip

# Restore backup
flask --app . backup-restore --from backup.zip --mode merge
```

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

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask secret key | `dev-secret-key-change-in-production` |
| `FLASK_DEBUG` | Enable debug mode | `False` |
| `DATABASE_URL` | Database connection string | `sqlite:///plugtrack.db` |
| `ENCRYPTION_KEY` | Encryption key for sensitive data | Required |

### Default Settings
The following settings are automatically seeded with sensible defaults:
- **petrol_threshold_p_per_kwh**: 52.5 (p/kWh threshold for petrol comparison)
- **default_efficiency_mpkwh**: 4.1 (fallback efficiency if car profile missing)
- **home_aliases_csv**: "home,house,garage" (location keywords for home detection)
- **home_charging_speed_kw**: 2.3 (default home charging speed)
- **petrol_price_p_per_litre**: 128.9 (current petrol price)
- **petrol_mpg**: 60.0 (petrol efficiency for comparisons)
- **allow_efficiency_fallback**: 1 (enable efficiency fallback logic)

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
│   ├── validators.py      # Validation and report types
│   ├── io_sessions.py     # CSV import/export service
│   ├── io_backup.py       # Backup/restore service
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
├── test_phase4.py         # Test suite
├── Dockerfile.dev          # Development Docker setup
└── docker-compose.dev.yml  # Development Docker Compose
```

## Development

### Docker Development Setup
```bash
# Build and run with Docker
docker-compose -f docker-compose.dev.yml up --build

# Access the application at http://localhost:5000
```

### Running Tests
```bash
python test_phase4.py
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions, please open an issue on the GitHub repository.

## Acknowledgments

- Flask community for the excellent web framework
- Bootstrap team for the responsive UI framework
- SQLAlchemy team for the powerful ORM
- Chart.js team for the interactive charting library
- Click team for the CLI framework
