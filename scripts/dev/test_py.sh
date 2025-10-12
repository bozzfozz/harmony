#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

TMP_DIR="$ROOT_DIR/.tmp"
mkdir -p "$TMP_DIR"
DB_FILE="$TMP_DIR/test.db"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$DB_FILE}"

./scripts/dev/auto_repair.py test
