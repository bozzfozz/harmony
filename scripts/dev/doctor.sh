#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

status=0

log_pass() {
  printf '[PASS] %s\n' "$1"
}

log_warn() {
  printf '[WARN] %s\n' "$1"
}

log_fail() {
  status=1
  printf '[FAIL] %s\n' "$1"
}

print_detail() {
  printf '%s\n' "$1" | sed 's/^/       /'
}

to_bool() {
  case "$1" in
    1|true|TRUE|True|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

resolve_python() {
  if command -v python >/dev/null 2>&1; then
    echo python
  elif command -v python3 >/dev/null 2>&1; then
    echo python3
  else
    echo ""
  fi
}

PYTHON_BIN=$(resolve_python)
if [[ -z "$PYTHON_BIN" ]]; then
  log_fail "python interpreter missing (install Python 3.10+)"
else
  version=$($PYTHON_BIN --version 2>&1 || true)
  log_pass "python available via ${PYTHON_BIN} (${version})"
fi

if command -v ruff >/dev/null 2>&1; then
  log_pass "ruff available"
else
  log_fail "ruff missing (install via 'pip install -r requirements-dev.txt')"
fi

if command -v pytest >/dev/null 2>&1; then
  log_pass "pytest available"
else
  log_fail "pytest missing (install via 'pip install -r requirements-test.txt')"
fi

check_directory() {
  local env_key=$1
  local fallback=$2
  local label=$3

  local raw_path="${!env_key:-$fallback}"
  if [[ -z "$raw_path" ]]; then
    log_fail "$label path not configured"
    return
  fi

  local path="$raw_path"
  if [[ "$path" == ~* ]]; then
    path="${path/#\~/$HOME}"
  fi

  if ! mkdir -p "$path" 2>/dev/null; then
    log_fail "$label directory not creatable ($path)"
    return
  fi

  if [[ ! -d "$path" ]]; then
    log_fail "$label path is not a directory ($path)"
    return
  fi

  if [[ ! -w "$path" || ! -x "$path" ]]; then
    log_fail "$label directory is not writable/executable ($path)"
    return
  fi

  local probe
  if ! probe=$(mktemp "$path/.doctor-probe.XXXXXX" 2>/dev/null); then
    log_fail "$label unable to create probe file ($path)"
    return
  fi

  if ! printf 'doctor-probe' >"$probe" 2>/dev/null; then
    rm -f "$probe" >/dev/null 2>&1 || true
    log_fail "$label unable to write probe file ($path)"
    return
  fi

  if ! cat "$probe" >/dev/null 2>&1; then
    rm -f "$probe" >/dev/null 2>&1 || true
    log_fail "$label unable to read probe file ($path)"
    return
  fi

  if ! rm -f "$probe" >/dev/null 2>&1; then
    log_fail "$label unable to clean probe file ($path)"
    return
  fi

  log_pass "$label directory ready ($path)"
}

check_directory DOWNLOADS_DIR /data/downloads "downloads"
check_directory MUSIC_DIR /data/music "music"

if [[ -n "$PYTHON_BIN" ]]; then
  if output=$($PYTHON_BIN -m pip check 2>&1); then
    log_pass "pip check"
  else
    log_fail "pip check"
    print_detail "$output"
  fi
else
  log_warn "pip check skipped (python missing)"
fi

if command -v pip-audit >/dev/null 2>&1; then
  if audit_output=$(pip-audit --disable-progress-bar -r requirements.txt 2>&1); then
    log_pass "pip-audit (requirements.txt)"
  else
    if printf '%s' "$audit_output" | grep -qiE 'network|connection|timed out|temporary failure|Name or service not known|offline'; then
      log_warn "pip-audit skipped (offline)"
      print_detail "$audit_output"
    else
      log_fail "pip-audit reported issues"
      print_detail "$audit_output"
    fi
  fi
else
  log_warn "pip-audit not installed; skipping security audit"
fi

if to_bool "${DOCTOR_PIP_REQS:-}"; then
  if command -v pip-missing-reqs >/dev/null 2>&1; then
    if output=$(pip-missing-reqs app tests 2>&1); then
      log_pass "pip-missing-reqs"
    else
      log_fail "pip-missing-reqs reported issues"
      print_detail "$output"
    fi
  else
    log_fail "pip-missing-reqs missing (required because DOCTOR_PIP_REQS=1)"
  fi

  if command -v pip-extra-reqs >/dev/null 2>&1; then
    requirements_args=(--requirements-file requirements.txt)
    [[ -f requirements-test.txt ]] && requirements_args+=(--requirements-file requirements-test.txt)
    [[ -f requirements-dev.txt ]] && requirements_args+=(--requirements-file requirements-dev.txt)
    if output=$(pip-extra-reqs "${requirements_args[@]}" app tests 2>&1); then
      log_pass "pip-extra-reqs"
    else
      log_fail "pip-extra-reqs reported issues"
      print_detail "$output"
    fi
  else
    log_fail "pip-extra-reqs missing (required because DOCTOR_PIP_REQS=1)"
  fi
else
  if command -v pip-missing-reqs >/dev/null 2>&1 && command -v pip-extra-reqs >/dev/null 2>&1; then
    log_warn "Requirement guard tooling detected but disabled (set DOCTOR_PIP_REQS=1 to enforce)"
  else
    log_warn "Requirement guard tooling not installed; set DOCTOR_PIP_REQS=1 to enforce"
  fi
fi

if [[ $status -ne 0 ]]; then
  echo "Doctor checks detected blocking issues." >&2
else
  echo "Doctor checks completed successfully."
fi

exit "$status"
