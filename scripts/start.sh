#!/bin/sh
set -eu

# Each environment uses one connection for migrations and the application.
: "${DATABASE_URL:?Set DATABASE_URL before starting the service}"
alembic upgrade head

# Reload remains opt-in for local development and is never enabled in production.
if [ "${ENVIRONMENT:-production}" = "development" ] && [ "${RELOAD:-false}" = "true" ]; then
  exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}" --reload
fi
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}"
