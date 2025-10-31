#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v pip-audit >/dev/null 2>&1; then
  printf 'pip-audit not found on PATH; attempting automatic installation.\n' >&2

  if [[ -n ${PIP_AUDIT_BOOTSTRAP:-} ]]; then
    read -r -a bootstrap_cmd <<<"${PIP_AUDIT_BOOTSTRAP}"
  else
    if [[ ! -f "requirements-dev.txt" ]]; then
      printf 'requirements-dev.txt is missing; cannot install pip-audit automatically.\n' >&2
      printf 'Install pip-audit manually via "pip install -r requirements-dev.txt".\n' >&2
      exit 1
    fi

    if command -v python3 >/dev/null 2>&1; then
      python_cmd="python3"
    elif command -v python >/dev/null 2>&1; then
      python_cmd="python"
    else
      printf 'Neither python3 nor python is available to install pip-audit.\n' >&2
      exit 1
    fi

    bootstrap_cmd=($python_cmd -m pip install -r requirements-dev.txt)
  fi

  bootstrap_display=$(printf '%q ' "${bootstrap_cmd[@]}")
  if ! "${bootstrap_cmd[@]}"; then
    printf 'Automatic installation of pip-audit failed using command: %s\n' "$bootstrap_display" >&2
    printf 'Install pip-audit manually via "pip install -r requirements-dev.txt" and retry.\n' >&2
    exit 1
  fi

  if ! command -v pip-audit >/dev/null 2>&1; then
    printf 'pip-audit is still unavailable after installation attempt.\n' >&2
    exit 1
  fi

  printf 'pip-audit installed successfully; continuing with vulnerability scans.\n' >&2
fi

help_output=""
if help_output=$(pip-audit --help 2>&1); then
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
    printf 'pip-audit does not support configuration files; running without %s.\n' "$config_file" >&2
  fi
fi

requirements_files=("requirements.txt")
[[ -f "requirements-dev.txt" ]] && requirements_files+=("requirements-dev.txt")
[[ -f "requirements-test.txt" ]] && requirements_files+=("requirements-test.txt")

# FastAPI 0.116.1 currently pins Starlette to <0.48.0, while
# GHSA-7f5h-v6xp-fcq8 is resolved in Starlette 0.49.1.
# Track the upstream resolution at https://github.com/advisories/GHSA-7f5h-v6xp-fcq8
# and remove this ignore once a compatible FastAPI release is available.
ignore_args=("--ignore-vuln" "GHSA-7f5h-v6xp-fcq8")

printf 'NOTE: Temporarily ignoring GHSA-7f5h-v6xp-fcq8 due to FastAPI/Starlette pinning.\n'

for req_file in "${requirements_files[@]}"; do
  printf '==> pip-audit (%s)\n' "$req_file"
  if audit_output=$(pip-audit "${audit_flags[@]}" "${config_args[@]}" --strict "${ignore_args[@]}" -r "$req_file" 2>&1); then
    printf '%s\n' "$audit_output"
  else
    printf '%s\n' "$audit_output" >&2
    if grep -qiE 'network|connection|timed out|temporary failure|Name or service not known|offline' <<<"$audit_output"; then
      printf 'pip-audit requires network connectivity to complete. Resolve connectivity issues before rerunning.\n' >&2
    else
      printf 'pip-audit detected vulnerabilities or encountered an error while scanning %s.\n' "$req_file" >&2
    fi
    exit 1
  fi
  printf '\n'
done
