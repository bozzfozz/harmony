#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v pip-audit >/dev/null 2>&1; then
  printf 'pip-audit is required for release checks. Install it via "pip install -r requirements-dev.txt".\n' >&2
  exit 1
fi

requirements_files=("requirements.txt")
[[ -f "requirements-dev.txt" ]] && requirements_files+=("requirements-dev.txt")
[[ -f "requirements-test.txt" ]] && requirements_files+=("requirements-test.txt")

for req_file in "${requirements_files[@]}"; do
  printf '==> pip-audit (%s)\n' "$req_file"
  if audit_output=$(pip-audit --disable-progress-bar -r "$req_file" 2>&1); then
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
