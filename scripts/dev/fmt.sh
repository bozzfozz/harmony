#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v ruff >/dev/null 2>&1; then
  echo "ruff is required but was not found in PATH. Install it via 'pip install ruff'." >&2
  exit 1
fi

ruff format .
ruff check --select I --fix .
