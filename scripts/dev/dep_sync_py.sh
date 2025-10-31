#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

ensure_uv_lock() {
  if uv lock --check >/dev/null 2>&1; then
    return
  fi

  if [[ -n ${CI:-} ]]; then
    echo "[dep-sync] uv.lock is outdated; run 'uv lock' locally and commit the result." >&2
    exit 1
  fi

  echo "[dep-sync] uv.lock out of date; regenerating via 'uv lock'." >&2
  uv lock
}

export_requirements() {
  local output_path=$1
  shift

  if ! uv export --locked --format requirements.txt --output-file "$output_path" "$@" >/dev/null 2>&1; then
    return 1
  fi

  if [[ ! -s "$output_path" ]]; then
    rm -f "$output_path"
    return 1
  fi

  return 0
}

ensure_uv_lock

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

runtime_requirements="$tmp_dir/runtime.txt"
if ! export_requirements "$runtime_requirements"; then
  echo "[dep-sync] Failed to export runtime dependencies via 'uv export'." >&2
  exit 1
fi

declare -a extra_requirement_files=()

dev_requirements="$tmp_dir/dev.txt"
if export_requirements "$dev_requirements" --only-group dev; then
  extra_requirement_files+=("$dev_requirements")
fi

test_requirements="$tmp_dir/test.txt"
if export_requirements "$test_requirements" --only-group test; then
  extra_requirement_files+=("$test_requirements")
fi

strict=false
case "${DOCTOR_PIP_REQS:-}" in
  1|true|TRUE|True|yes|YES|on|ON)
    strict=true
    ;;
esac

if ! command -v pip-missing-reqs >/dev/null 2>&1; then
  if [[ "$strict" == true ]]; then
    echo "pip-missing-reqs is required when DOCTOR_PIP_REQS=1. Install it via 'pip install pip_check_reqs'." >&2
    exit 1
  fi
  echo "[dep-sync] pip-missing-reqs not installed; skipping missing-requirements scan." >&2
else
  pip-missing-reqs app tests
fi

if ! command -v pip-extra-reqs >/dev/null 2>&1; then
  if [[ "$strict" == true ]]; then
    echo "pip-extra-reqs is required when DOCTOR_PIP_REQS=1. Install it via 'pip install pip_check_reqs'." >&2
    exit 1
  fi
  echo "[dep-sync] pip-extra-reqs not installed; skipping extra-requirements scan." >&2
else
  requirements_args=(--requirements-file "$runtime_requirements")
  for req_file in "${extra_requirement_files[@]}"; do
    requirements_args+=(--requirements-file "$req_file")
  done
  pip-extra-reqs "${requirements_args[@]}" app tests
fi
