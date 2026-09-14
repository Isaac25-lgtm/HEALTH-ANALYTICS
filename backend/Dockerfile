# One image for the API, the Celery worker and one-off migration jobs.
# Worker dependencies (Celery + Redis client) are always installed so the API can dispatch
# and the worker can consume from the same build.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system hpip && useradd --system --gid hpip --home-dir /app --no-create-home hpip

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
RUN pip install ".[worker]" \
    && mkdir -p /app/export_artifacts /app/data \
    && chown -R hpip:hpip /app/export_artifacts /app/data

# Production posture by default. Every credential and endpoint must come from the environment;
# the API and worker refuse to start in production when required settings are missing.
ENV APP_ENV=production \
    EXPORT_DIR=/app/export_artifacts \
    EXPORT_EAGER=false \
    RATE_LIMIT_BACKEND=redis \
    SYNC_EXECUTION=queue

USER hpip
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=40s --retries=3 \
    CMD ["python", "scripts/healthcheck.py"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
