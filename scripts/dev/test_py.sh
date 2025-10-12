#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v pytest >/dev/null 2>&1; then
  echo "pytest is required but was not found in PATH. Install it via 'pip install pytest'." >&2
  exit 1
fi

TMP_DIR="$ROOT_DIR/.tmp"
mkdir -p "$TMP_DIR"
DB_FILE="$TMP_DIR/test.db"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$DB_FILE}"

pytest -q
