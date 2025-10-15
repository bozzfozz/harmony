#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v rg >/dev/null 2>&1; then
  echo "ripgrep (rg) is required to run the UI guard." >&2
  exit 1
fi

TARGETS=("app/ui/templates" "app/ui/static")
FORBIDDEN_PATTERNS=(
  "TODO"
  "FIXME"
  "TBD"
  "TKTK"
  "LOREM IPSUM"
  "REPLACE_ME"
  "REPLACE ME"
  "CHANGEME"
  "FPO"
  "@@"
)

VIOLATIONS=0
TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT

for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
  if rg --ignore-case --no-heading --line-number --with-filename --fixed-strings "$pattern" "${TARGETS[@]}" >"$TMP_FILE"; then
    echo "Forbidden placeholder pattern '$pattern' detected:" >&2
    cat "$TMP_FILE" >&2
    VIOLATIONS=1
  fi
  : >"$TMP_FILE"
done

if rg --pcre2 --no-heading --line-number --with-filename "hx-(?:get|post|put|patch|delete)\s*=\s*[\"']/api/" app/ui/templates >"$TMP_FILE"; then
  echo "HTMX calls targeting '/api/…' are forbidden for UI templates." >&2
  cat "$TMP_FILE" >&2
  VIOLATIONS=1
fi

: >"$TMP_FILE"
REQUIRED_ASSETS=(
  "app/ui/static/css/app.css"
  "app/ui/static/js/htmx.min.js"
  "app/ui/static/icons.svg"
)

for asset in "${REQUIRED_ASSETS[@]}"; do
  if [[ ! -s "$asset" ]]; then
    echo "Required static asset missing or empty: $asset" >&2
    VIOLATIONS=1
  fi
done

if [[ $VIOLATIONS -ne 0 ]]; then
  exit 1
fi

echo "UI guard checks passed."
