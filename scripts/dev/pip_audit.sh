#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

pip_audit_cmd=(uv run --frozen pip-audit)

if ! command -v "${pip_audit_cmd[0]}" >/dev/null 2>&1; then
  printf 'pip-audit runner "%s" not found on PATH. Install uv >= 0.7 and retry.\n' "${pip_audit_cmd[0]}" >&2
  exit 1
fi

help_command=(uv run --no-sync pip-audit --help)

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

config_file=".pip-audit.toml"
config_args=()
if [[ -f "$config_file" ]]; then
  if [[ -n $help_output && $help_output == *"--config"* ]]; then
    config_args=("-c" "$config_file")
  else
    printf 'pip-audit runner does not support configuration files; running without %s.\n' "$config_file" >&2
  fi
fi

if audit_output=$("${pip_audit_cmd[@]}" "${audit_flags[@]}" "${config_args[@]}" --strict); then
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
