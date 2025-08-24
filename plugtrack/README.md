# PlugTrack - EV Charging Session Manager

PlugTrack is a personal web application for logging and managing EV charging sessions and car profiles. Built with Python Flask, it provides a comprehensive solution for tracking your electric vehicle charging habits, costs, and efficiency.

## Features

### Phase 1 (Current)
- **User Management**: Secure authentication with password hashing
- **Car Profiles**: Manage multiple vehicles with battery capacity and efficiency tracking
- **Charging Sessions**: Log detailed charging sessions with cost tracking
- **Dashboard**: Overview of active car and recent charging sessions
- **Settings**: Configurable home charging rates and placeholders for future features
- **Data Export**: CSV export functionality for charging sessions

### Future Phases
- **Notifications**: Gotify/Apprise integration
- **AI Integration**: OpenAI/Anthropic API integration for insights
- **PWA Support**: Progressive Web App capabilities
- **Advanced Analytics**: Cost trends, efficiency analysis, and recommendations

## Technology Stack

- **Backend**: Python 3.8+, Flask 3.0
- **Database**: SQLite with SQLAlchemy ORM
- **Frontend**: Bootstrap 5, HTML5, CSS3, JavaScript
- **Authentication**: Flask-Login with secure password hashing
- **Security**: Encryption service for sensitive data
- **Migrations**: Flask-Migrate for database schema management

## Installation

### Prerequisites
- Python 3.8 or higher
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
   flask init-db
   ```

7. **Run the application**
   ```bash
   python run.py
   ```

## Usage

### Default Login
After running `flask init-db`, you can log in with:
- **Username**: `demo`
- **Password**: `demo123`

### Creating a New User
```bash
flask create-admin
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
│   └── settings.py        # User settings
├── routes/                 # Flask routes/views
│   ├── __init__.py
│   ├── auth.py            # Authentication routes
│   ├── cars.py            # Car management
│   ├── charging_sessions.py # Session management
│   ├── settings.py        # Settings management
│   └── dashboard.py       # Dashboard view
├── services/               # Business logic
│   ├── __init__.py
│   ├── encryption.py      # Data encryption
│   └── forms.py           # Form definitions
├── templates/              # HTML templates
│   ├── base.html          # Base template
│   ├── auth/              # Authentication templates
│   ├── cars/              # Car management templates
│   ├── charging_sessions/ # Session templates
│   ├── settings/          # Settings templates
│   └── dashboard/         # Dashboard templates
├── static/                 # Static assets
│   ├── css/               # Stylesheets
│   └── js/                # JavaScript
├── config.py               # Configuration
├── run.py                  # Application entry point
└── requirements.txt        # Python dependencies
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask secret key | `dev-secret-key-change-in-production` |
| `FLASK_DEBUG` | Enable debug mode | `False` |
| `DATABASE_URL` | Database connection string | `sqlite:///plugtrack.db` |
| `ENCRYPTION_KEY` | Encryption key for sensitive data | Required |

### Database Configuration
The application uses SQLite by default, but you can configure other databases by updating the `DATABASE_URL` environment variable.

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

### Phase 2
- Advanced analytics and reporting
- Mobile-responsive improvements
- API endpoints for external integrations

### Phase 3
- PWA implementation
- Offline functionality
- Advanced notification system

### Phase 4
- Multi-user support
- Data import/export
- Integration with EV charging networks

## Support

For support and questions, please open an issue on the GitHub repository.

## Acknowledgments

- Flask community for the excellent web framework
- Bootstrap team for the responsive UI framework
- SQLAlchemy team for the powerful ORM
