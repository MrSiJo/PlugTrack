# Copilot Instructions for PlugTrack

## Project Overview
PlugTrack is a Flask-based web application designed to manage EV charging sessions. It features advanced analytics, smart reminders, and cost analysis. The project is built using Python 3.11+, Flask 3.0, SQLite/SQLAlchemy, and Bootstrap 5.

## Core Architecture

### Flask Application Structure
- **Blueprint-based Modular Architecture**: Each functional area is encapsulated in its own blueprint (e.g., `auth`, `cars`, `charging_sessions`, `settings`, `dashboard`, `analytics`).
- **Blueprint Registration**: Blueprints are imported and registered in `__init__.py` with appropriate URL prefixes.
- **Authentication**: Use the `@login_required` decorator for protected routes and `current_user` for user-specific operations.

### Database Models
- **Location**: Models are stored in the `models/` directory.
- **Examples**: Key models include `user.py`, `car.py`, `charging_session.py`, `settings.py`, and `session_meta.py`.
- **ORM**: SQLAlchemy is used for database interactions.

### Frontend
- **Framework**: Bootstrap 5 is used for responsive design.
- **Templates**: HTML templates are located in the `templates/` directory.
- **Static Files**: CSS, JavaScript, and images are stored in the `static/` directory.

## Developer Workflows

### Setting Up the Environment
1. Clone the repository.
2. Create a virtual environment: `python -m venv venv`.
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - macOS/Linux: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`.

### Running the Application
- Use the `run.py` script to start the development server: `python run.py`.

### Database Migrations
- Initialize the database: `python init_db.py`.
- Apply migrations: `python migrate.py`.

### Testing
- Run unit tests: `pytest tests/`.

## Project-Specific Conventions
- **Code Style**: Follow PEP 8 guidelines.
- **Blueprints**: Each blueprint should encapsulate a single functional area.
- **Database Models**: Place all models in the `models/` directory and ensure they are well-documented.
- **Routes**: Define routes in the `routes/` directory, grouped by functionality.

## Integration Points
- **Database**: SQLite is used for local development; ensure migrations are up-to-date.
- **Frontend**: Templates and static files are tightly integrated with Flask's rendering engine.
- **External APIs**: Document any external API dependencies in the `AGENTS.md` file.

## References
- [AGENTS.md](plugtrack/AGENTS.md): Detailed repository guidelines.
- [README.md](README.md): General project information and contribution guidelines.
- [MIGRATION_SUMMARY.md](.cursor/rules/MIGRATION_SUMMARY.md): Details on the migration system modernization.

---

For any questions or clarifications, please refer to the `README.md` or open an issue in the repository.