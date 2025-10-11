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

FRONTEND_DIST_DIR="/app/frontend_dist"
RUNTIME_TEMPLATE_PATH="${FRONTEND_DIST_DIR}/env.runtime.js.tpl"

if [ -f "${RUNTIME_TEMPLATE_PATH}" ]; then
  echo "Generating frontend runtime configuration from ${RUNTIME_TEMPLATE_PATH}..."
  python3 <<'PYTHON'
import json
import os
from pathlib import Path
from string import Template

frontend_dist_dir = Path("/app/frontend_dist")
template_path = frontend_dist_dir / "env.runtime.js.tpl"
output_path = frontend_dist_dir / "env.runtime.js"

def escape_js_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')

backend_url = os.environ.get("PUBLIC_BACKEND_URL", "")
sentry_dsn = os.environ.get("PUBLIC_SENTRY_DSN", "")
feature_flags_raw = os.environ.get("PUBLIC_FEATURE_FLAGS", "")

if feature_flags_raw.strip():
    try:
        feature_flags = json.dumps(json.loads(feature_flags_raw))
    except json.JSONDecodeError:
        print(
            "Warning: PUBLIC_FEATURE_FLAGS is not valid JSON; defaulting to empty object.",
            flush=True,
        )
        feature_flags = "{}"
else:
    feature_flags = "{}"

template_content = template_path.read_text(encoding="utf-8")
rendered = Template(template_content).safe_substitute(
    PUBLIC_BACKEND_URL=escape_js_string(backend_url),
    PUBLIC_SENTRY_DSN=escape_js_string(sentry_dsn),
    PUBLIC_FEATURE_FLAGS=feature_flags,
)

output_path.write_text(rendered, encoding="utf-8")
PYTHON
else
  echo "Frontend runtime config template not found at ${RUNTIME_TEMPLATE_PATH}; skipping generation."
fi

echo "Starting application: $*"
exec "$@"
