#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if [ -f scripts/dev/sync_runtime_requirements.py ]; then
  if [ -n "${CI:-}" ]; then
    python scripts/dev/sync_runtime_requirements.py --check
  else
    python scripts/dev/sync_runtime_requirements.py --write
  fi
fi

strict=false
case "${DOCTOR_PIP_REQS:-}" in
  1|true|TRUE|True|yes|YES|on|ON)
    strict=true
    ;;
esac

if ! command -v pip-missing-reqs >/dev/null 2>&1; then
  if [ "$strict" = true ]; then
    echo "pip-missing-reqs is required when DOCTOR_PIP_REQS=1. Install it via 'pip install pip_check_reqs'." >&2
    exit 1
  fi
  echo "[dep-sync] pip-missing-reqs not installed; skipping missing-requirements scan." >&2
else
  pip-missing-reqs app tests
fi

if ! command -v pip-extra-reqs >/dev/null 2>&1; then
  if [ "$strict" = true ]; then
    echo "pip-extra-reqs is required when DOCTOR_PIP_REQS=1. Install it via 'pip install pip_check_reqs'." >&2
    exit 1
  fi
  echo "[dep-sync] pip-extra-reqs not installed; skipping extra-requirements scan." >&2
else
  requirements_args=(--requirements-file requirements.txt)
  [[ -f requirements-test.txt ]] && requirements_args+=(--requirements-file requirements-test.txt)
  [[ -f requirements-dev.txt ]] && requirements_args+=(--requirements-file requirements-dev.txt)
  pip-extra-reqs "${requirements_args[@]}" app tests
fi
