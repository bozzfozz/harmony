#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

WHEEL_CACHE_DIR=${UI_SMOKE_WHEEL_DIR:-$ROOT_DIR/.cache/ui-smoke-wheels}

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo "python is required to run UI smoke checks." >&2
  exit 1
fi

if command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  PYTHON_BIN=python3
fi

ensure_runtime_dependency() {
  local module=$1
  local requirement=$2

  if $PYTHON_BIN -c "import ${module}" >/dev/null 2>&1; then
    return 0
  fi

  local cache_has_artifacts=0
  if [[ -d "$WHEEL_CACHE_DIR" ]] && compgen -G "$WHEEL_CACHE_DIR/*" >/dev/null 2>&1; then
    cache_has_artifacts=1
  fi

  if [[ $cache_has_artifacts -eq 1 ]]; then
    echo "Installing ${requirement} from cached wheels in $WHEEL_CACHE_DIR" >&2
    if "$PYTHON_BIN" -m pip install --no-index --find-links="$WHEEL_CACHE_DIR" "$requirement"; then
      if $PYTHON_BIN -c "import ${module}" >/dev/null 2>&1; then
        return 0
      fi
      echo "Installed ${requirement} from cache but the ${module} module is still unavailable." >&2
    else
      echo "Failed to install ${requirement} from cache. Falling back to PyPI." >&2
    fi
  fi

  echo "Attempting to install ${requirement} from PyPI." >&2
  if "$PYTHON_BIN" -m pip install "$requirement"; then
    if $PYTHON_BIN -c "import ${module}" >/dev/null 2>&1; then
      return 0
    fi
  fi

  cat >&2 <<ERROR
Unable to import ${module}. Please ensure the dependency is available.
If network access is restricted, pre-download the runtime wheels using
  scripts/dev/cache_ui_smoke_wheels.sh
and set UI_SMOKE_WHEEL_DIR to point at the cache.
ERROR
  exit 1
}

ensure_runtime_dependency uvicorn "uvicorn==0.30.1"
ensure_runtime_dependency httpx "httpx==0.27.0"

readarray -t RUNTIME_VALUES < <($PYTHON_BIN <<'PY'
from app.config import load_runtime_env, resolve_app_port

env = load_runtime_env()
port = resolve_app_port(env)
print(port)
PY
)

if [[ ${#RUNTIME_VALUES[@]} -lt 1 ]]; then
  echo "Failed to resolve APP_PORT from runtime environment." >&2
  exit 1
fi

PORT=${RUNTIME_VALUES[0]//[$'\r\n ']}
if [[ -z "$PORT" || ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "Resolved APP_PORT ('$PORT') is not a valid integer." >&2
  exit 1
fi

TMP_DIR="$ROOT_DIR/.tmp"
mkdir -p "$TMP_DIR"
LOG_FILE="$TMP_DIR/ui-smoke.log"
: >"$LOG_FILE"
DB_FILE="$TMP_DIR/ui-smoke.db"

export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$DB_FILE}"
export HARMONY_API_KEYS="${HARMONY_API_KEYS:-ui-smoke-key}"
export HARMONY_DISABLE_WORKERS=${HARMONY_DISABLE_WORKERS:-1}
export UI_ROLE_DEFAULT="${UI_ROLE_DEFAULT:-operator}"
export DOWNLOADS_DIR="${DOWNLOADS_DIR:-$TMP_DIR/downloads}"
export MUSIC_DIR="${MUSIC_DIR:-$TMP_DIR/music}"
mkdir -p "$DOWNLOADS_DIR" "$MUSIC_DIR"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && ps -p "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

$PYTHON_BIN -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!

LISTEN_MARKER="listening on 0.0.0.0:${PORT} path=/live"
RETRIES=60
while (( RETRIES > 0 )); do
  if grep -Fq "$LISTEN_MARKER" "$LOG_FILE" 2>/dev/null; then
    break
  fi
  if ! ps -p "$SERVER_PID" >/dev/null 2>&1; then
    echo "Backend terminated before binding. Logs:" >&2
    tail -n 200 "$LOG_FILE" >&2 || true
    exit 1
  fi
  sleep 1
  RETRIES=$((RETRIES - 1))
  if (( RETRIES == 0 )); then
    echo "Backend failed to start within timeout." >&2
    tail -n 200 "$LOG_FILE" >&2 || true
    exit 1
  fi
done

BASE_URL="http://127.0.0.1:${PORT}"
export BASE_URL

if ! $PYTHON_BIN <<'PY'
import asyncio
import os
import re
import sys

import httpx

BASE_URL = os.environ["BASE_URL"]
API_KEY = os.environ.get("HARMONY_API_KEYS", "ui-smoke-key")
PLACEHOLDER_PATTERNS = [
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bTBD\b",
    r"TKTK",
    r"LOREM\s+IPSUM",
    r"REPLACE[_ ]ME",
    r"CHANGEME",
    r"FPO",
    r"@@",
]


def ensure_html(response: httpx.Response, path: str) -> None:
    ctype = response.headers.get("content-type", "")
    if "text/html" not in ctype:
        raise AssertionError(f"{path} did not return HTML: {ctype!r}")
    body = response.text
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, body, flags=re.IGNORECASE):
            raise AssertionError(f"Placeholder pattern {pattern!r} present in {path}")


def extract_csrf(response: httpx.Response) -> str | None:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.text)
    return match.group(1) if match else None


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        live = await client.get("/live")
        live.raise_for_status()

        login_page = await client.get("/ui/login")
        if login_page.status_code != 200:
            raise AssertionError("/ui/login did not return 200")
        ensure_html(login_page, "/ui/login")

        login = await client.post("/ui/login", data={"api_key": API_KEY})
        if login.status_code != 303:
            raise AssertionError(f"/ui/login expected 303, got {login.status_code}")
        session_cookie = login.cookies.get("ui_session")
        csrf_cookie = login.cookies.get("csrftoken")
        if session_cookie:
            client.cookies.set("ui_session", session_cookie)
        if csrf_cookie:
            client.cookies.set("csrftoken", csrf_cookie)

        dashboard = await client.get("/ui/")
        if dashboard.status_code != 200:
            raise AssertionError(f"/ui/ expected 200, got {dashboard.status_code}")
        ensure_html(dashboard, "/ui/")
        dashboard_csrf_cookie = dashboard.cookies.get("csrftoken")
        if dashboard_csrf_cookie:
            client.cookies.set("csrftoken", dashboard_csrf_cookie)
        csrf_token = extract_csrf(dashboard) or dashboard_csrf_cookie

        fragment_paths = [
            "/ui/activity/table",
            "/ui/downloads/table",
            "/ui/watchlist/table",
            "/ui/jobs/table",
        ]
        for path in fragment_paths:
            response = await client.get(path)
            if response.status_code != 200:
                raise AssertionError(f"{path} expected 200, got {response.status_code}")
            ensure_html(response, path)

        if csrf_token:
            headers = {"X-CSRF-Token": csrf_token}
            watchlist_post = await client.post(
                "/ui/watchlist",
                data={"artist_key": "spotify:artist:ui-smoke"},
                headers=headers,
            )
            if watchlist_post.status_code not in {200, 400}:
                raise AssertionError(
                    f"/ui/watchlist returned unexpected status {watchlist_post.status_code}"
                )
            if watchlist_post.status_code == 200:
                ensure_html(watchlist_post, "/ui/watchlist (POST)")

asyncio.run(main())
PY
then
  echo "UI smoke checks failed. Dumping logs:" >&2
  tail -n 200 "$LOG_FILE" >&2 || true
  exit 1
fi

echo "UI smoke checks passed."
