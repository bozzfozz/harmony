#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! uv lock --check >/dev/null 2>&1; then
  printf '[pip-audit] uv.lock is out of date. Run "uv lock" and commit the result before auditing.\n' >&2
  exit 1
fi

declare -a pip_audit_cmd
if [[ -n ${PIP_AUDIT_CMD:-} ]]; then
  # shellcheck disable=SC2206
  pip_audit_cmd=($PIP_AUDIT_CMD)
else
  pip_audit_cmd=(uvx pip-audit)
fi

if ! command -v "${pip_audit_cmd[0]}" >/dev/null 2>&1; then
  printf 'pip-audit runner "%s" not found on PATH. Install uv >= 0.7 and retry.\n' "${pip_audit_cmd[0]}" >&2
  exit 1
fi

help_output=""
if help_output=$("${pip_audit_cmd[@]}" --help 2>&1); then
  if grep -q -- '--progress-spinner' <<<"$help_output"; then
    audit_flags=("--progress-spinner" "off")
  elif grep -q -- '--disable-progress-bar' <<<"$help_output"; then
    audit_flags=("--disable-progress-bar")
  else
    audit_flags=()
  fi
else
  printf 'Unable to determine supported pip-audit flags; proceeding without optional arguments.\n' >&2
  audit_flags=()
fi

config_args=()
config_file=".pip-audit.toml"
if [[ -f "$config_file" ]]; then
  if [[ -n $help_output && $help_output == *"--config"* ]]; then
    config_args=("-c" "$config_file")
  else
    printf 'pip-audit runner does not support configuration files; running without %s.\n' "$config_file" >&2
  fi
fi

export_requirements() {
  local label=$1
  local output_path=$2
  shift 2

  if ! uv export --locked --format requirements.txt --output-file "$output_path" "$@" >/dev/null 2>&1; then
    return 1
  fi

  if [[ ! -s "$output_path" ]]; then
    rm -f "$output_path"
    return 1
  fi

  printf '%s\n' "$label"
}

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

declare -a audit_labels=()
declare -a audit_files=()

runtime_requirements="$tmp_dir/runtime.txt"
if export_requirements "Runtime dependencies" "$runtime_requirements"; then
  audit_labels+=("Runtime dependencies")
  audit_files+=("$runtime_requirements")
else
  printf '[pip-audit] Failed to export runtime dependencies via uv.\n' >&2
  exit 1
fi

dev_requirements="$tmp_dir/dev.txt"
if export_requirements "Development dependencies" "$dev_requirements" --only-group dev; then
  audit_labels+=("Development dependencies")
  audit_files+=("$dev_requirements")
fi

test_requirements="$tmp_dir/test.txt"
if export_requirements "Test dependencies" "$test_requirements" --only-group test; then
  audit_labels+=("Test dependencies")
  audit_files+=("$test_requirements")
fi

# FastAPI 0.116.1 currently pins Starlette to <0.48.0, while
# GHSA-7f5h-v6xp-fcq8 is resolved in Starlette 0.49.1.
# Track the upstream resolution at https://github.com/advisories/GHSA-7f5h-v6xp-fcq8
# and remove this ignore once a compatible FastAPI release is available.
ignore_args=("--ignore-vuln" "GHSA-7f5h-v6xp-fcq8")

printf 'NOTE: Temporarily ignoring GHSA-7f5h-v6xp-fcq8 due to FastAPI/Starlette pinning.\n'

for idx in "${!audit_files[@]}"; do
  label=${audit_labels[$idx]}
  req_file=${audit_files[$idx]}
  printf '==> pip-audit (%s)\n' "$label"
  if audit_output=$("${pip_audit_cmd[@]}" "${audit_flags[@]}" "${config_args[@]}" --strict "${ignore_args[@]}" -r "$req_file" 2>&1); then
    printf '%s\n' "$audit_output"
  else
    printf '%s\n' "$audit_output" >&2
    if grep -qiE 'network|connection|timed out|temporary failure|Name or service not known|offline' <<<"$audit_output"; then
      printf 'pip-audit requires network connectivity to complete. Resolve connectivity issues before rerunning.\n' >&2
    else
      printf 'pip-audit detected vulnerabilities or encountered an error while scanning %s.\n' "$label" >&2
    fi
    exit 1
  fi
  printf '\n'
done
