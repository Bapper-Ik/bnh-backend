#!/bin/sh
set -eu

# The migration connection owns schema changes; DATABASE_URL stays restricted.
: "${MIGRATION_DATABASE_URL:?Set MIGRATION_DATABASE_URL before starting the service}"
alembic upgrade head
# The web process does not need the migration owner's credentials.
unset MIGRATION_DATABASE_URL

# Reload remains opt-in for local development and is never enabled in production.
if [ "${ENVIRONMENT:-production}" = "development" ] && [ "${RELOAD:-false}" = "true" ]; then
  exec uvicorn app.vendor_app:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}" --reload
fi
exec uvicorn app.vendor_app:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}"
