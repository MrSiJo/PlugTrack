# Contributing to PlugTrack v2 backend

## Pre-commit hooks

After cloning the repo, install the pre-commit hooks once:

```bash
pip install pre-commit
pre-commit install
```

Hooks that run on every commit:

- **gitleaks** — secret scanning
- **bandit** (`-ll`) — security linter, scoped to `backend/`
- **ruff** — lint with `--fix`
- **ruff-format** — formatter check
- **forbid-environment-ips** — blocks RFC 1918 IP literals (`10.x.x.x`,
  `172.16-31.x.x`, `192.168.x.x`) outside `legacy/` and `docs/`

The `security-invariants` hook is **manual-stage** and not triggered
automatically. Run it before merging anything that touches auth, CSRF,
or settings:

```bash
pre-commit run --hook-stage manual security-invariants
```

## Running tests

```bash
cd backend
pytest tests -v
```
