#!/usr/bin/env sh
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="sqlite+aiosqlite:///data/harmony.db"
  echo "DATABASE_URL not provided; using ${DATABASE_URL}."
fi

case "${DATABASE_URL}" in
  sqlite+aiosqlite://*|sqlite+pysqlite://*|sqlite://*)
    ;;
  *)
    echo "Error: DATABASE_URL must use a sqlite driver (sqlite+aiosqlite:/// or sqlite+pysqlite:///)." >&2
    exit 1
    ;;
esac

python3 <<'PYTHON'
import os
from pathlib import Path

from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
path = url.database
if path and path != ":memory:":
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
PYTHON

echo "Starting application: $*"
exec "$@"
