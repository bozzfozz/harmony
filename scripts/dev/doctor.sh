#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

status=0

have_uv=false
if command -v uv >/dev/null 2>&1; then
  have_uv=true
fi

export_requirements() {
  local output_path=$1
  shift

  if ! $have_uv; then
    return 1
  fi

  if ! uv export --locked --format requirements.txt --output-file "$output_path" "$@" >/dev/null 2>&1; then
    return 1
  fi

  if [[ ! -s "$output_path" ]]; then
    rm -f "$output_path"
    return 1
  fi

  return 0
}

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
  log_fail "ruff missing (install via 'uv sync --group dev' or 'uv tool install ruff')"
fi

if command -v pytest >/dev/null 2>&1; then
  log_pass "pytest available"
else
  log_fail "pytest missing (install via 'uv sync --group test' or 'uv tool install pytest')"
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

check_directory DOWNLOADS_DIR /downloads "downloads"
check_directory MUSIC_DIR /music "music"

if [[ -n "$PYTHON_BIN" ]]; then
  if $have_uv; then
    if output=$(uv pip check --python "$PYTHON_BIN" 2>&1); then
      log_pass "uv pip check"
    else
      log_fail "uv pip check"
      print_detail "$output"
    fi
  else
    log_warn "uv pip check skipped (uv not available)"
  fi
else
  log_warn "uv pip check skipped (python missing)"
fi

if $have_uv; then
  audit_log=$(mktemp)
  if scripts/dev/pip_audit.sh >"$audit_log" 2>&1; then
    log_pass "pip-audit (uv.lock)"
  else
    log_fail "pip-audit reported issues"
    print_detail "$(cat "$audit_log")"
  fi
  rm -f "$audit_log"
else
  log_warn "pip-audit skipped (uv not available)"
fi

if to_bool "${DOCTOR_PIP_REQS:-}"; then
  if ! $have_uv; then
    log_fail "Requirement guard tooling requires uv (install via 'uv sync --group dev')"
  else
    if output=$(uv run --locked --with pip-check-reqs pip-missing-reqs app tests 2>&1); then
      log_pass "pip-missing-reqs"
    else
      log_fail "pip-missing-reqs reported issues"
      print_detail "$output"
    fi

    tmp_dir=$(mktemp -d)
    runtime_requirements="$tmp_dir/runtime.txt"
    if ! export_requirements "$runtime_requirements"; then
      rm -rf "$tmp_dir"
      log_fail "pip-extra-reqs prerequisites missing (uv export failed)"
    else
      requirements_args=(--requirements-file "$runtime_requirements")

      dev_requirements="$tmp_dir/dev.txt"
      if export_requirements "$dev_requirements" --only-group dev; then
        requirements_args+=(--requirements-file "$dev_requirements")
      fi

      test_requirements="$tmp_dir/test.txt"
      if export_requirements "$test_requirements" --only-group test; then
        requirements_args+=(--requirements-file "$test_requirements")
      fi

      if output=$(uv run --locked --with pip-check-reqs pip-extra-reqs "${requirements_args[@]}" app tests 2>&1); then
        log_pass "pip-extra-reqs"
      else
        log_fail "pip-extra-reqs reported issues"
        print_detail "$output"
      fi
      rm -rf "$tmp_dir"
    fi
  fi
else
  if $have_uv; then
    log_warn "Requirement guard tooling disabled (set DOCTOR_PIP_REQS=1 to enforce)"
  else
    log_warn "Requirement guard tooling requires uv (install via 'uv sync --group dev')"
  fi
fi

if [[ $status -ne 0 ]]; then
  echo "Doctor checks detected blocking issues." >&2
else
  echo "Doctor checks completed successfully."
fi

exit "$status"
