#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo "python is required to download runtime wheels." >&2
  exit 1
fi

if command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  PYTHON_BIN=python3
fi

DEST_DIR=${1:-${UI_SMOKE_WHEEL_DIR:-$ROOT_DIR/.cache/ui-smoke-wheels}}
mkdir -p "$DEST_DIR"

PACKAGES=(
  "uvicorn==0.30.6"
  "httpx==0.27.0"
)

cat <<INFO
Caching UI smoke runtime wheels into: $DEST_DIR
Using python executable: $PYTHON_BIN
Packages: ${PACKAGES[*]}
INFO

"$PYTHON_BIN" -m pip download \
  --dest "$DEST_DIR" \
  "${PACKAGES[@]}"

echo "Download complete. The wheel cache now contains:"
if compgen -G "$DEST_DIR/*" >/dev/null 2>&1; then
  for artifact in "$DEST_DIR"/*; do
    if [[ -f "$artifact" ]]; then
      printf '  %s\n' "$(basename "$artifact")"
    fi
  done | sort
else
  echo "  (empty)"
fi
