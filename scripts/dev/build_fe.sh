#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
FRONTEND_DIR="$ROOT_DIR/frontend"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "frontend directory not found at $FRONTEND_DIR" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but was not found in PATH. Install Node.js (includes npm)." >&2
  exit 1
fi

cd "$FRONTEND_DIR"

npm ci --no-audit --no-fund
npm run build
