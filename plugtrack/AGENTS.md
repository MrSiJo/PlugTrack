# Repository Guidelines

## Project Structure & Module Organization
PlugTrack is a Flask app rooted in this package; `create_app` wires blueprints in `routes/` and SQLAlchemy models in `models/`. Shared business logic sits in `services/` while helper utilities live in `utils/`. HTML templates and static assets live in `templates/` and `static/`. Database setup scripts and Alembic helpers sit under `migrations/`, with tooling in `migrate.py`. Tests live in `tests/` and `unit-tests/`.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` — create and activate a virtualenv.
- `pip install -r requirements.txt` — install Flask, SQLAlchemy, and supporting libraries.
- `python -m plugtrack` — launch the development server.
- `flask --app run.py init-db` — bootstrap a demo SQLite database and seed sample data.
- `python migrate.py status` / `python migrate.py init --dry-run` — inspect or apply structured migrations.
- `pytest tests unit-tests` — run the full suite; add `-k name` to focus a failing test module.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation and descriptive snake_case names for modules, functions, and variables. SQLAlchemy models use PascalCase (example: `ChargingSession`). Prefer explicit imports from sibling packages and keep blueprints modular—register logic inside `routes/*` instead of `__init__.py`. Type hints are welcome for new services; pair them with short docstrings describing intent, especially when manipulating metrics or onboarding flows.

## Testing Guidelines
Pytest is the standard. Unit specs live in `unit-tests/`, while scenario coverage and API assertions live in `tests/`. Mirror the module under test in your filename (e.g. `tests/test_session_metrics_api.py`). Run `pytest --maxfail=1` locally before opening a PR; add fixtures or factories instead of seeding ad-hoc data. Use `python migrate.py test` when changes touch schema orchestration.

## Commit & Pull Request Guidelines
Commits in this repo use concise, sentence-case imperatives (`Enhance onboarding and user experience in Phase 7`). Group related edits per commit, referencing migrations or fixtures when they change. PRs should explain the user impact, list validation commands run, and link any tracking issues. Include screenshots or JSON snippets when UI charts, reminders, or analytics exports change so reviewers can verify behaviour quickly.

## Configuration & Security Notes
Copy `env_example.txt` to `.env` and update secrets locally; never commit real credentials. The default SQLite files reside in `instance/`; inspect them before sharing debug bundles. Prefer environment variables over inline constants for API keys, and rotate the `SECRET_KEY` in production deployments.
