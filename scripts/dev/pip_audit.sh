#!/usr/bin/env bash
set -euo pipefail

# FastAPI 0.116.1 currently pins Starlette to <0.48.0, while
# GHSA-7f5h-v6xp-fcq8 is resolved in Starlette 0.49.1.
# Track the upstream resolution at https://github.com/advisories/GHSA-7f5h-v6xp-fcq8
# and remove this ignore once a compatible FastAPI release is available.
ignore_args=("--ignore-vuln" "GHSA-7f5h-v6xp-fcq8")

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
  pip_audit_cmd=(uv run --locked pip-audit)
fi

if ! command -v "${pip_audit_cmd[0]}" >/dev/null 2>&1; then
  printf 'pip-audit runner "%s" not found on PATH. Install uv >= 0.7 and retry.\n' "${pip_audit_cmd[0]}" >&2
  exit 1
fi

help_command=("${pip_audit_cmd[@]}")
if [[ ${pip_audit_cmd[0]} == "uv" ]]; then
  help_command+=("--" "--help")
else
  help_command+=("--help")
fi

help_output=""
if help_output=$("${help_command[@]}" 2>&1); then
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

printf 'NOTE: Temporarily ignoring GHSA-7f5h-v6xp-fcq8 due to FastAPI/Starlette pinning.\n'

if audit_output=$("${pip_audit_cmd[@]}" "${audit_flags[@]}" "${config_args[@]}" --strict "${ignore_args[@]}"); then
  printf '%s\n' "$audit_output"
else
  printf '%s\n' "$audit_output" >&2
  if grep -qiE 'network|connection|timed out|temporary failure|Name or service not known|offline' <<<"$audit_output"; then
    printf 'pip-audit requires network connectivity to complete. Resolve connectivity issues before rerunning.\n' >&2
  else
    printf 'pip-audit detected vulnerabilities or encountered an error while scanning dependencies.\n' >&2
  fi
  exit 1
fi
