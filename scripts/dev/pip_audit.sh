#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  printf 'uv is required to run pip-audit. Install uv >= 0.7 and retry.\n' >&2
  exit 1
fi

audit_cmd=(
  uv run --no-sync pip-audit
  --progress-spinner=off
  --ignore-vuln GHSA-7f5h-v6xp-fcq8
  --strict
)

if "${audit_cmd[@]}"; then
  exit 0
fi

status=$?
if (( status == 1 )); then
  printf 'pip-audit reported vulnerabilities or policy violations.\n' >&2
  exit 2
fi

printf 'pip-audit execution failed with exit code %d.\n' "$status" >&2
exit "$status"
