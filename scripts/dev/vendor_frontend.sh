#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
IMPORT_MAP_PATH="${ROOT_DIR}/frontend/importmap.json"
STATIC_IMPORT_MAP_PATH="${ROOT_DIR}/frontend/static/importmap.json"
VENDOR_DIR="${ROOT_DIR}/frontend/static/vendor"
MODE="vendor"

export ROOT_DIR
export IMPORT_MAP_PATH
export STATIC_IMPORT_MAP_PATH
export VENDOR_DIR

if [[ $# -gt 0 ]]; then
  case "$1" in
    --reset)
      MODE="reset"
      ;;
    --vendor)
      MODE="vendor"
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--vendor|--reset]" >&2
      exit 1
      ;;
  esac
fi

if [[ ! -f "${IMPORT_MAP_PATH}" ]]; then
  echo "Import map not found at ${IMPORT_MAP_PATH}" >&2
  exit 1
fi

mkdir -p "${VENDOR_DIR}"

if [[ "${MODE}" == "reset" ]]; then
  find "${VENDOR_DIR}" -type f -delete
  cp "${IMPORT_MAP_PATH}" "${STATIC_IMPORT_MAP_PATH}"
  echo "Reset import map to CDN mode." >&2
  exit 0
fi

python3 <<'PYTHON'
import json
import os
import sys
import urllib.request
from pathlib import Path

root_dir = Path(os.environ["ROOT_DIR"])
import_map_path = Path(os.environ["IMPORT_MAP_PATH"])
static_import_map_path = Path(os.environ["STATIC_IMPORT_MAP_PATH"])
vendor_dir = Path(os.environ["VENDOR_DIR"])

with import_map_path.open("r", encoding="utf-8") as fh:
    import_map = json.load(fh)

imports = import_map.get("imports", {})
if not isinstance(imports, dict):
    raise SystemExit("Import map 'imports' must be a JSON object")

vendor_dir.mkdir(parents=True, exist_ok=True)

local_imports = {}

for specifier, target in imports.items():
    if not isinstance(target, str):
        raise SystemExit(f"Import target for {specifier!r} must be a string")
    if target.startswith("/static/"):
        local_imports[specifier] = target
        continue
    if not target.startswith(("https://", "http://")):
        local_imports[specifier] = target
        continue
    safe_name = specifier.replace("/", "__")
    if not safe_name:
        raise SystemExit(f"Empty specifier encountered in import map")
    destination = vendor_dir / f"{safe_name}.js"
    print(f"Downloading {target} → {destination}")
    request = urllib.request.Request(target, headers={"User-Agent": "harmony-vendor-script/1.0"})
    with urllib.request.urlopen(request) as response:  # noqa: S310
        destination.write_bytes(response.read())
    local_imports[specifier] = f"/static/vendor/{destination.name}"

local_map = {"imports": {**imports, **local_imports}}
static_import_map_path.write_text(json.dumps(local_map, indent=2) + "\n", encoding="utf-8")
PYTHON

echo "Vendored frontend dependencies to ${VENDOR_DIR} and updated import map." >&2
