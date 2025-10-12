#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

status=0

check_command() {
  local cmd=$1
  local hint=$2
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[missing] $cmd — $hint" >&2
    status=1
  else
    echo "[ok] $cmd"
  fi
}

resolve_python() {
  if command -v python >/dev/null 2>&1; then
    echo python
  elif command -v python3 >/dev/null 2>&1; then
    echo python3
  else
    echo "" 
  fi
}

PYTHON_BIN=$(resolve_python)
if [[ -z "$PYTHON_BIN" ]]; then
  echo "[missing] python — install Python 3.10+." >&2
  status=1
else
  echo "[ok] $PYTHON_BIN"
fi

check_command ruff "install via 'pip install ruff'"
check_command pytest "install via 'pip install pytest'"
check_command pip-missing-reqs "install via 'pip install pip-check-reqs'"
check_command pip-extra-reqs "install via 'pip install pip-check-reqs'"

required_dirs=(/data/downloads /data/music)
for path in "${required_dirs[@]}"; do
  if [[ ! -d "$path" ]]; then
    echo "[missing] directory $path — create it and ensure the current user has write permissions." >&2
    status=1
    continue
  fi
  if [[ ! -w "$path" ]]; then
    echo "[denied] directory $path — grant write access to the current user." >&2
    status=1
  else
    echo "[ok] directory $path writable"
  fi
done

if [[ $status -ne 0 ]]; then
  echo "Doctor checks failed. Resolve the issues above." >&2
  exit 1
fi

echo "All doctor checks passed."
