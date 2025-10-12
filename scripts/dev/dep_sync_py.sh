#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v pip-missing-reqs >/dev/null 2>&1; then
  echo "pip-missing-reqs is required. Install it via 'pip install pip-check-reqs'." >&2
  exit 1
fi

if ! command -v pip-extra-reqs >/dev/null 2>&1; then
  echo "pip-extra-reqs is required. Install it via 'pip install pip-check-reqs'." >&2
  exit 1
fi

pip-missing-reqs app tests
pip-extra-reqs --requirements-file requirements.txt app tests
