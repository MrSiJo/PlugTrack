# syntax=docker/dockerfile:1.7
# PlugTrack backend container.
#
# Single-stage build of the FastAPI app. Python 3.12-slim base, tini for
# clean PID-1 signal handling, runs as a non-root `app` user, exposes 9278.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY plugtrack ./plugtrack

RUN mkdir -p /app/data /app/logs \
    && chown -R app:app /app

USER app

EXPOSE 9278

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9278/api/health', timeout=3).status == 200 else 1)" \
    || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "plugtrack.main:create_app", "--host", "0.0.0.0", "--port", "9278", "--factory"]
