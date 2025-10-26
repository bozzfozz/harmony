#!/usr/bin/env bash
set -eEuo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

log_info() {
  echo "[smoke-lsio] $1" >&2
}

log_warn() {
  echo "[smoke-lsio][warn] $1" >&2
}

log_error() {
  echo "[smoke-lsio][error] $1" >&2
}

fail() {
  local message="$1"
  log_error "$message"
  return 1
}

require_command() {
  local binary="$1"
  if ! command -v "$binary" >/dev/null 2>&1; then
    fail "Required command '$binary' is not available in PATH"
  fi
}

CONTAINER_NAME=${HARMONY_LSIO_CONTAINER_NAME:-harmony-lsio}
IMAGE_NAME=${HARMONY_LSIO_IMAGE_NAME:-ghcr.io/bozzfozz/harmony:lsio}
HOST_PORT=${HARMONY_LSIO_SMOKE_PORT:-18080}
TMP_ROOT="$ROOT_DIR/.tmp/lsio-smoke"
CONFIG_DIR="$TMP_ROOT/config"
DOWNLOADS_DIR="$TMP_ROOT/downloads"
MUSIC_DIR="$TMP_ROOT/music"
HEALTHCHECK_URL="http://127.0.0.1:${HOST_PORT}/api/health/ready"
MAX_WAIT_SECONDS=60
CONTAINER_STARTED=0
FAILED=0

handle_error() {
  local exit_code="$1"
  local line_no="$2"
  FAILED=1
  log_error "Execution failed at line ${line_no} (exit=${exit_code})"
  dump_container_state || true
  dump_host_state || true
  exit "$exit_code"
}
trap 'handle_error $? $LINENO' ERR

cleanup() {
  if [[ $CONTAINER_STARTED -eq 1 ]] && command -v docker >/dev/null 2>&1; then
    if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
      docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
  fi
  if [[ $FAILED -eq 0 ]]; then
    log_info "Cleanup complete."
  else
    log_warn "Cleanup after failure complete."
  fi
}
trap cleanup EXIT

container_is_running() {
  docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"
}

dump_container_state() {
  if ! command -v docker >/dev/null 2>&1; then
    log_warn "Docker unavailable for diagnostics"
    return 0
  fi
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    log_warn "--- docker ps (matching container) ---"
    docker ps -a --filter "name=${CONTAINER_NAME}" >&2 || true
    log_warn "--- docker logs (last 200 lines) ---"
    docker logs --tail=200 "$CONTAINER_NAME" >&2 || true
    log_warn "--- docker inspect (State excerpt) ---"
    docker inspect "$CONTAINER_NAME" | sed -n '1,80p' >&2 || true
  else
    log_warn "Container ${CONTAINER_NAME} not found for diagnostics"
  fi
}

dump_host_state() {
  log_warn "--- host filesystem snapshot (.tmp/lsio-smoke) ---"
  if [[ -d "$TMP_ROOT" ]]; then
    find "$TMP_ROOT" -maxdepth 2 -type f -print >&2 || true
  else
    log_warn "Temporary directory ${TMP_ROOT} missing"
  fi
}

if [[ "${HARMONY_LSIO_SMOKE_DRY_RUN:-0}" == "1" ]]; then
  log_info "Dry run requested - skipping Docker execution"
  exit 0
fi

if [[ "${HARMONY_LSIO_SMOKE_FORCE_FAIL:-0}" == "1" ]]; then
  fail "Forced failure requested via HARMONY_LSIO_SMOKE_FORCE_FAIL"
fi

require_command docker
require_command curl

mkdir -p "$CONFIG_DIR" "$DOWNLOADS_DIR" "$MUSIC_DIR"
rm -f "$CONFIG_DIR/harmony.db"

PUID=${PUID:-$(id -u)}
PGID=${PGID:-$(id -g)}
TZ=${TZ:-Etc/UTC}

log_info "Starting container ${CONTAINER_NAME} from ${IMAGE_NAME}"
CONTAINER_ID=$(docker run --rm -d \
  --name "$CONTAINER_NAME" \
  -p "${HOST_PORT}:8080" \
  -e PUID="$PUID" \
  -e PGID="$PGID" \
  -e TZ="$TZ" \
  -v "$CONFIG_DIR:/config" \
  -v "$DOWNLOADS_DIR:/downloads" \
  -v "$MUSIC_DIR:/music" \
  "$IMAGE_NAME")
CONTAINER_STARTED=1
log_info "Container started with ID ${CONTAINER_ID}"

wait_seconds=$MAX_WAIT_SECONDS
while (( wait_seconds > 0 )); do
  if curl --fail --silent "$HEALTHCHECK_URL" >/dev/null 2>&1; then
    log_info "Healthcheck succeeded"
    break
  fi
  if ! container_is_running; then
    fail "Container ${CONTAINER_NAME} exited before readiness"
  fi
  sleep 1
  wait_seconds=$((wait_seconds - 1))
done

if (( wait_seconds == 0 )); then
  fail "Container did not become ready within ${MAX_WAIT_SECONDS}s"
fi

log_info "Checking database presence inside container"
docker exec -w / "$CONTAINER_NAME" ls -l ./config/harmony.db >&2 || fail "Database file missing inside container"

if [[ ! -f "$CONFIG_DIR/harmony.db" ]]; then
  fail "Expected database file not found at ${CONFIG_DIR}/harmony.db"
fi

log_info "Database snapshot on host:"
ls -l "$CONFIG_DIR/harmony.db" >&2

log_info "Smoke test succeeded"
