#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

PYTHON_BIN=""
if command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  echo "python is required but was not found in PATH." >&2
  exit 1
fi

if ! $PYTHON_BIN -c "import uvicorn" >/dev/null 2>&1; then
  echo "uvicorn is required. Install backend dependencies via 'pip install -r requirements.txt'." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to perform smoke checks." >&2
  exit 1
fi

DEFAULT_CLIENT_HOST=${SMOKE_HOST:-127.0.0.1}
if [[ -n "${SMOKE_SERVER_HOST:-}" ]]; then
  SERVER_HOST=${SMOKE_SERVER_HOST}
elif [[ -n "${SMOKE_HOST:-}" ]]; then
  SERVER_HOST=${SMOKE_HOST}
else
  SERVER_HOST=0.0.0.0
fi

CLIENT_HOST=${SMOKE_CLIENT_HOST:-$DEFAULT_CLIENT_HOST}
readarray -t RUNTIME_VALUES < <($PYTHON_BIN <<'PY'
from app.config import load_runtime_env, resolve_app_port

env = load_runtime_env()
port = resolve_app_port(env)
path_value = (env.get("SMOKE_PATH") or "/live").strip()
if not path_value.startswith("/"):
    path_value = f"/{path_value}"
print(port)
print(path_value or "/live")
PY
)

if [[ ${#RUNTIME_VALUES[@]} -lt 2 ]]; then
  echo "Failed to resolve APP_PORT/SMOKE_PATH from runtime environment." >&2
  exit 1
fi

PORT=${RUNTIME_VALUES[0]//[$'\r\n ']}
PATH_SUFFIX=${RUNTIME_VALUES[1]//[$'\r\n ']}

if [[ -z "$PORT" || ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "Resolved APP_PORT ('$PORT') is not a valid integer." >&2
  exit 1
fi

if [[ -z "$PATH_SUFFIX" ]]; then
  PATH_SUFFIX=/live
fi

export APP_PORT="$PORT"
export SMOKE_PATH="$PATH_SUFFIX"

echo "Smoke test targeting http://${CLIENT_HOST}:${PORT}${PATH_SUFFIX} (server bind ${SERVER_HOST})" >&2
TMP_DIR="$ROOT_DIR/.tmp"
mkdir -p "$TMP_DIR"
DB_FILE="$TMP_DIR/smoke.db"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$DB_FILE}"
export HARMONY_DISABLE_WORKERS=${HARMONY_DISABLE_WORKERS:-1}
export INTEGRATIONS_ENABLED=${INTEGRATIONS_ENABLED:-spotify}
export HARMONY_API_KEYS=${HARMONY_API_KEYS:-smoke-key}
export SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID:-smoke-client}
export SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET:-smoke-secret}
export OAUTH_SPLIT_MODE=${OAUTH_SPLIT_MODE:-false}
export SLSKD_HOST=${SLSKD_HOST:-localhost}
export SLSKD_PORT=${SLSKD_PORT:-5030}
export DOWNLOADS_DIR=${DOWNLOADS_DIR:-$TMP_DIR/downloads}
export MUSIC_DIR=${MUSIC_DIR:-$TMP_DIR/music}
mkdir -p "$DOWNLOADS_DIR" "$MUSIC_DIR"

SMOKE_LOG="$TMP_DIR/smoke.log"
: > "$SMOKE_LOG"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && ps -p "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

dump_local_diagnostics() {
  echo "--- process snapshot ---" >&2
  if [[ -n "${SERVER_PID:-}" ]]; then
    ps -p "$SERVER_PID" -o pid,ppid,stat,etime,args >&2 || true
  else
    ps -eo pid,ppid,stat,etime,args | head -n 5 >&2 || true
  fi
  echo "--- listening sockets ---" >&2
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp >&2 || true
  elif command -v netstat >/dev/null 2>&1; then
    netstat -tlnp >&2 || true
  else
    echo "ss/netstat not available" >&2
  fi
}

$PYTHON_BIN -m uvicorn app.main:app --host "$SERVER_HOST" --port "$PORT" >"$SMOKE_LOG" 2>&1 &
SERVER_PID=$!

LISTEN_MARKER="listening on 0.0.0.0:${PORT} path=/live"
LISTEN_RETRIES=60
while (( LISTEN_RETRIES > 0 )); do
  if grep -Fq "$LISTEN_MARKER" "$SMOKE_LOG" 2>/dev/null; then
    break
  fi
  if ! ps -p "$SERVER_PID" >/dev/null 2>&1; then
    echo "Backend process terminated before binding. Logs:" >&2
    cat "$SMOKE_LOG" >&2
    dump_local_diagnostics
    exit 1
  fi
  sleep 1
  LISTEN_RETRIES=$((LISTEN_RETRIES - 1))
done

RETRIES=30
until curl --fail --silent --show-error "http://$CLIENT_HOST:$PORT${PATH_SUFFIX}" >/dev/null 2>&1; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    echo "Backend failed to become ready. Logs:" >&2
    cat "$SMOKE_LOG" >&2
    dump_local_diagnostics
    exit 1
  fi
  sleep 1
  if ! ps -p "$SERVER_PID" >/dev/null 2>&1; then
    echo "Backend process terminated unexpectedly. Logs:" >&2
    cat "$SMOKE_LOG" >&2
    exit 1
  fi
done

echo "Backend smoke check passed: ${PATH_SUFFIX} returned 200."

if command -v docker >/dev/null 2>&1; then
  IMAGE=${SMOKE_UNIFIED_IMAGE:-harmony-unified:local}
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Running optional unified image smoke for $IMAGE" >&2
    CONTAINER_NAME="harmony-smoke-$RANDOM"
    docker run --rm --name "$CONTAINER_NAME" -d -p 0:"$PORT" "$IMAGE" >/dev/null
    CONTAINER_PORT=$(docker port "$CONTAINER_NAME" "${PORT}/tcp" | head -n1 | awk -F: '{print $2}')
    if [[ -z "$CONTAINER_PORT" ]]; then
      echo "Failed to determine mapped port for $IMAGE" >&2
      docker logs "$CONTAINER_NAME" >&2 || true
      docker exec "$CONTAINER_NAME" ss -tlnp >&2 || docker exec "$CONTAINER_NAME" netstat -tlnp >&2 || true
      docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 1
    fi
    DOCKER_RETRIES=30
    until curl --fail --silent --show-error "http://127.0.0.1:$CONTAINER_PORT${PATH_SUFFIX}" >/dev/null 2>&1; do
      DOCKER_RETRIES=$((DOCKER_RETRIES - 1))
      if [[ $DOCKER_RETRIES -le 0 ]]; then
        echo "Docker smoke check failed for $IMAGE" >&2
        docker logs "$CONTAINER_NAME" >&2 || true
        docker exec "$CONTAINER_NAME" ss -tlnp >&2 || docker exec "$CONTAINER_NAME" netstat -tlnp >&2 || true
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
        exit 1
      fi
      sleep 1
    done
    echo "Docker smoke check passed for $IMAGE."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  else
    echo "Docker not configured with image $IMAGE; skipping optional container smoke." >&2
  fi
else
  echo "docker command not found; skipping optional container smoke." >&2
fi
