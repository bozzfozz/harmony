#!/usr/bin/env bash
set -euo pipefail

should_skip_smoke() {
  local raw="${SMOKE_ENABLED:-}"
  if [[ -z "$raw" ]]; then
    return 1
  fi

  local normalized="${raw,,}"
  # strip common whitespace characters to allow values like " false "
  normalized="${normalized//[$'\t\n\r ']}"

  case "$normalized" in
    0|false|no|off|skip|disabled)
      echo "Smoke checks disabled via SMOKE_ENABLED=${raw}" >&2
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if should_skip_smoke; then
  exit 0
fi

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
  echo "uvicorn is required. Install backend dependencies via 'uv sync' before running the smoke test." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to perform smoke checks." >&2
  exit 1
fi

normalize_guard_mode() {
  local value="${1,,}"
  case "$value" in
    0|off|skip|disabled|false)
      echo "off"
      ;;
    strict|require|required|1|true)
      echo "strict"
      ;;
    warn|soft|default|on|auto|*)
      echo "warn"
      ;;
  esac
}

if [[ -n "${SMOKE_SERVER_HOST:-}" ]]; then
  SERVER_HOST=${SMOKE_SERVER_HOST}
elif [[ -n "${SMOKE_HOST:-}" ]]; then
  SERVER_HOST=${SMOKE_HOST}
else
  SERVER_HOST=0.0.0.0
fi

CLIENT_HOST=127.0.0.1
readarray -t RUNTIME_VALUES < <($PYTHON_BIN <<'PY'
from app.config import load_runtime_env, resolve_app_port

env = load_runtime_env()
port = resolve_app_port(env)
path_value = (env.get("SMOKE_PATH") or "/api/health/live").strip()
if not path_value.startswith("/"):
    path_value = f"/{path_value}"
print(port)
print(path_value or "/api/health/live")
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
  PATH_SUFFIX=/api/health/live
fi

export APP_PORT="$PORT"
export SMOKE_PATH="$PATH_SUFFIX"

TARGET_URL="http://${CLIENT_HOST}:${PORT}${PATH_SUFFIX}"
echo "Smoke test targeting ${TARGET_URL} (server bind ${SERVER_HOST})" >&2
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

SELFCHECK_MODE_RAW=${SMOKE_SELFCHECK:-warn}
SELFCHECK_MODE=$(normalize_guard_mode "$SELFCHECK_MODE_RAW")
if [[ "$SELFCHECK_MODE" != "off" ]]; then
  echo "Running startup self-check (--assert-startup) [mode=$SELFCHECK_MODE_RAW]" >&2
  if "$PYTHON_BIN" -m app.ops.selfcheck --assert-startup; then
    echo "Startup self-check passed." >&2
  else
    echo "Startup self-check failed." >&2
    if [[ "$SELFCHECK_MODE" == "strict" ]]; then
      exit 1
    fi
  fi
fi

SMOKE_LOG="$TMP_DIR/smoke.log"
: > "$SMOKE_LOG"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && ps -p "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

dump_smoke_log() {
  echo "--- backend logs (last 200 lines) ---" >&2
  if [[ -f "$SMOKE_LOG" ]]; then
    tail -n 200 "$SMOKE_LOG" >&2 || true
  else
    echo "smoke log missing at $SMOKE_LOG" >&2
  fi
}

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

dump_container_diagnostics() {
  local container="$1"
  echo "--- docker logs (last 200 lines) ---" >&2
  docker logs --tail=200 "$container" >&2 || true
  echo "--- docker process list ---" >&2
  docker exec "$container" sh -c 'ps -ef || true' >&2 || true
  echo "--- docker listening sockets ---" >&2
  docker exec "$container" sh -c 'ss -ltnp || netstat -ltnp || true' >&2 || true
  echo "--- docker environment (APP_PORT/PORT) ---" >&2
  docker exec "$container" sh -c 'printenv | sort | sed -n "s/^\(APP_PORT\|PORT\)=.*/&/p"' >&2 || true
}

$PYTHON_BIN -m uvicorn app.main:app --host "$SERVER_HOST" --port "$PORT" >"$SMOKE_LOG" 2>&1 &
SERVER_PID=$!

LISTEN_MARKER="listening on 0.0.0.0:${PORT}"
LISTEN_RETRIES=60
while (( LISTEN_RETRIES > 0 )); do
  if grep -Fq "$LISTEN_MARKER" "$SMOKE_LOG" 2>/dev/null; then
    break
  fi
  if ! ps -p "$SERVER_PID" >/dev/null 2>&1; then
    echo "Backend process terminated before binding. Logs:" >&2
    dump_smoke_log
    dump_local_diagnostics
    exit 1
  fi
  sleep 1
  LISTEN_RETRIES=$((LISTEN_RETRIES - 1))
done

RETRIES=30
until curl --fail --silent --show-error "$TARGET_URL" >/dev/null 2>&1; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    echo "Backend failed to become ready. Logs:" >&2
    dump_smoke_log
    dump_local_diagnostics
    exit 1
  fi
  sleep 2
  if ! ps -p "$SERVER_PID" >/dev/null 2>&1; then
    echo "Backend process terminated unexpectedly. Logs:" >&2
    dump_smoke_log
    dump_local_diagnostics
    exit 1
  fi
done

echo "Backend smoke check passed: ${PATH_SUFFIX} returned 200."

READY_CHECK_MODE=${SMOKE_READY_CHECK:-warn}
READY_PATH_SUFFIX=${SMOKE_READY_PATH:-/api/health/ready?verbose=1}
if [[ -n "$READY_PATH_SUFFIX" && "${READY_PATH_SUFFIX:0:1}" != "/" ]]; then
  READY_PATH_SUFFIX="/${READY_PATH_SUFFIX}"
fi

READY_MODE=$(normalize_guard_mode "$READY_CHECK_MODE")

if [[ "$READY_MODE" != "off" ]]; then
  READY_URL="http://${CLIENT_HOST}:${PORT}${READY_PATH_SUFFIX}"
  echo "Probing readiness endpoint ${READY_URL}" >&2
  READY_RETRIES=30
  until curl --fail --silent --show-error "$READY_URL" >/dev/null 2>&1; do
    READY_RETRIES=$((READY_RETRIES - 1))
    if [[ $READY_RETRIES -le 0 ]]; then
      echo "Backend readiness check failed. Logs:" >&2
      dump_smoke_log
      dump_local_diagnostics
      if [[ "$READY_MODE" == "strict" ]]; then
        exit 1
      fi
      echo "Readiness probe failed but continuing because SMOKE_READY_CHECK=${READY_CHECK_MODE}." >&2
      READY_MODE="warn_failed"
      break
    fi
    sleep 2
    if ! ps -p "$SERVER_PID" >/dev/null 2>&1; then
      echo "Backend process terminated unexpectedly during readiness check. Logs:" >&2
      dump_smoke_log
      dump_local_diagnostics
      if [[ "$READY_MODE" == "strict" ]]; then
        exit 1
      fi
      echo "Backend exited during readiness probe; continuing because SMOKE_READY_CHECK=${READY_CHECK_MODE}." >&2
      READY_MODE="warn_failed"
      break
    fi
  done
  if [[ "$READY_MODE" == "warn" ]]; then
    echo "Backend readiness check passed: ${READY_PATH_SUFFIX} returned 200."
  elif [[ "$READY_MODE" == "warn_failed" ]]; then
    echo "Backend readiness check completed with failures (non-strict mode)." >&2
  else
    echo "Backend readiness check passed: ${READY_PATH_SUFFIX} returned 200."
  fi
fi

if command -v docker >/dev/null 2>&1; then
  IMAGE=${SMOKE_UNIFIED_IMAGE:-harmony-unified:local}
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Running optional unified image smoke for $IMAGE" >&2
    CONTAINER_NAME="harmony-smoke-$RANDOM"
    docker run --rm --name "$CONTAINER_NAME" -d -p 0:"$PORT" "$IMAGE" >/dev/null
    CONTAINER_PORT=$(docker port "$CONTAINER_NAME" "${PORT}/tcp" | head -n1 | awk -F: '{print $2}')
    if [[ -z "$CONTAINER_PORT" ]]; then
      echo "Failed to determine mapped port for $IMAGE" >&2
      dump_container_diagnostics "$CONTAINER_NAME"
      docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 1
    fi
    DOCKER_RETRIES=30
    until curl --fail --silent --show-error "http://127.0.0.1:$CONTAINER_PORT${PATH_SUFFIX}" >/dev/null 2>&1; do
      DOCKER_RETRIES=$((DOCKER_RETRIES - 1))
      if [[ $DOCKER_RETRIES -le 0 ]]; then
        echo "Docker smoke check failed for $IMAGE" >&2
        dump_container_diagnostics "$CONTAINER_NAME"
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
        exit 1
      fi
      sleep 2
    done
    echo "Docker smoke check passed for $IMAGE."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  else
    echo "Docker not configured with image $IMAGE; skipping optional container smoke." >&2
  fi
else
  echo "docker command not found; skipping optional container smoke." >&2
fi
