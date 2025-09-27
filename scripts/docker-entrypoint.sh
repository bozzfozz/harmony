#!/usr/bin/env sh
set -euo pipefail

if [ "${FEATURE_RUN_MIGRATIONS:-on}" != "off" ]; then
  echo "Applying database migrations..."
  alembic upgrade head
else
  echo "Skipping database migrations (FEATURE_RUN_MIGRATIONS=${FEATURE_RUN_MIGRATIONS:-off})."
fi

echo "Starting application: $*"
exec "$@"
