#!/usr/bin/env sh
set -euo pipefail

ATTEMPTS=${POSTGRES_WAIT_ATTEMPTS:-60}
SLEEP_SECONDS=${POSTGRES_WAIT_INTERVAL:-1}

derive_from_url() {
  if [ -z "${DATABASE_URL:-}" ]; then
    return 1
  fi

  python3 <<'PYTHON' || return 1
import os
from sqlalchemy.engine import make_url

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit(1)

try:
    parsed = make_url(url)
except Exception:
    raise SystemExit(1)

host = parsed.host or ""
port = str(parsed.port or "")
username = parsed.username or ""

print(f"{host}\n{port}\n{username}")
PYTHON
}

HOST=${POSTGRES_HOST:-}
PORT=${POSTGRES_PORT:-}
USER=${POSTGRES_USER:-}

if output=$(derive_from_url 2>/dev/null); then
  IFS="\n" read -r derived_host derived_port derived_user <<EOF
$output
EOF
  if [ -z "$HOST" ] && [ -n "$derived_host" ]; then
    HOST=$derived_host
  fi
  if [ -z "$PORT" ] && [ -n "$derived_port" ]; then
    PORT=$derived_port
  fi
  if [ -z "$USER" ] && [ -n "$derived_user" ]; then
    USER=$derived_user
  fi
fi

HOST=${HOST:-localhost}
PORT=${PORT:-5432}
USER=${USER:-postgres}

echo "Waiting for PostgreSQL at ${HOST}:${PORT} as ${USER} (max ${ATTEMPTS} attempts)..."

for attempt in $(seq 1 "$ATTEMPTS"); do
  if pg_isready --host="$HOST" --port="$PORT" --username="$USER" >/dev/null 2>&1; then
    echo "PostgreSQL is ready."
    exit 0
  fi
  sleep "$SLEEP_SECONDS"
done

echo "PostgreSQL did not become ready in time." >&2
exit 1
