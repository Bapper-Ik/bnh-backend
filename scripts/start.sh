#!/bin/sh
set -eu
# Run only the committed feature assembly. Reload is opt-in for local development.
if [ "${ENVIRONMENT:-production}" = "development" ] && [ "${RELOAD:-false}" = "true" ]; then
  exec uvicorn app.vendor_app:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}" --reload
fi
exec uvicorn app.vendor_app:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}"
