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
npx eslint "src/**/*.{ts,tsx,js,jsx}" --max-warnings=0

TMP_REPORT=$(mktemp)
trap 'rm -f "$TMP_REPORT"' EXIT

npx depcheck --skip-missing --json > "$TMP_REPORT"

python - <<'PY' "$TMP_REPORT"
import json
import sys

report_path = sys.argv[1]
with open(report_path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

unused = data.get("unusedDependencies") or []
missing = data.get("missing") or {}
invalid_files = data.get("invalidFiles") or {}

errors: list[str] = []
if unused:
    deps = ", ".join(sorted(unused))
    errors.append(f"Unused dependencies detected: {deps}")
if missing:
    formatted = ", ".join(f"{pkg}: {', '.join(sorted(paths))}" for pkg, paths in sorted(missing.items()))
    errors.append(f"Missing dependencies detected: {formatted}")
if invalid_files:
    issues = ", ".join(sorted(invalid_files.keys()))
    errors.append(f"Depcheck reported invalid files: {issues}")

if errors:
    for line in errors:
        print(line, file=sys.stderr)
    sys.exit(1)
PY
