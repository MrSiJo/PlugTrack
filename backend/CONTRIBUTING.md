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
- **forbid-environment-ips** — blocks RFC 1918 IP literals
  (`10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`) from being committed.

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

### Integration tests (real Cupra account)

`backend/tests/integration/` contains tests that hit the real Cupra
Connect cloud via pycupra. They are **gated** — skipped unless both:

- `INTEGRATION=1` is set in the environment, AND
- `.env.probe` exists at the repo root with valid Cupra credentials
  (`CUPRA_USERNAME` + `CUPRA_PASSWORD`; `CUPRA_SPIN` optional).

`.env.probe` is gitignored. **Never commit it.**

Run integration tests after pycupra version bumps:

```bash
INTEGRATION=1 pytest backend/tests/integration -v
```

The default `pytest backend/tests` invocation skips them.
