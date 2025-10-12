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

HOST=${SMOKE_HOST:-127.0.0.1}
PORT=${SMOKE_PORT:-8080}
TMP_DIR="$ROOT_DIR/.tmp"
mkdir -p "$TMP_DIR"
DB_FILE="$TMP_DIR/smoke.db"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$DB_FILE}"
export HARMONY_DISABLE_WORKERS=${HARMONY_DISABLE_WORKERS:-1}

SMOKE_LOG="$TMP_DIR/smoke.log"
: > "$SMOKE_LOG"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && ps -p "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

$PYTHON_BIN -m uvicorn app.main:app --host "$HOST" --port "$PORT" >"$SMOKE_LOG" 2>&1 &
SERVER_PID=$!

RETRIES=30
until curl --fail --silent --show-error "http://$HOST:$PORT/api/health/live" >/dev/null 2>&1; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    echo "Backend failed to become ready. Logs:" >&2
    cat "$SMOKE_LOG" >&2
    exit 1
  fi
  sleep 1
  if ! ps -p "$SERVER_PID" >/dev/null 2>&1; then
    echo "Backend process terminated unexpectedly. Logs:" >&2
    cat "$SMOKE_LOG" >&2
    exit 1
  fi
done

echo "Backend smoke check passed: /api/health/live returned 200."

if command -v docker >/dev/null 2>&1; then
  IMAGE=${SMOKE_UNIFIED_IMAGE:-harmony-unified:local}
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Running optional unified image smoke for $IMAGE" >&2
    CONTAINER_NAME="harmony-smoke-$RANDOM"
    docker run --rm --name "$CONTAINER_NAME" -d -p 0:8080 "$IMAGE" >/dev/null
    CONTAINER_PORT=$(docker port "$CONTAINER_NAME" 8080/tcp | head -n1 | awk -F: '{print $2}')
    if [[ -z "$CONTAINER_PORT" ]]; then
      echo "Failed to determine mapped port for $IMAGE" >&2
      docker logs "$CONTAINER_NAME" >&2 || true
      docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 1
    fi
    DOCKER_RETRIES=30
    until curl --fail --silent --show-error "http://127.0.0.1:$CONTAINER_PORT/api/health/live" >/dev/null 2>&1; do
      DOCKER_RETRIES=$((DOCKER_RETRIES - 1))
      if [[ $DOCKER_RETRIES -le 0 ]]; then
        echo "Docker smoke check failed for $IMAGE" >&2
        docker logs "$CONTAINER_NAME" >&2 || true
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
