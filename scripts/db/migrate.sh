#!/usr/bin/env sh
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WAIT_SCRIPT="${SCRIPT_DIR}/wait-for-postgres.sh"

if [ "${WAIT_FOR_POSTGRES:-on}" != "off" ]; then
  "${WAIT_SCRIPT}"
fi

echo "Running Alembic migrations..."
alembic upgrade head
