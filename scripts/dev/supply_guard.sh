#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "${ROOT_DIR}"

status=0

error() {
  echo "[supply-guard][ERROR] $1" >&2
  status=1
}

info() {
  echo "[supply-guard][INFO] $1" >&2
}

check_forbidden_artifacts() {
  local forbidden=(
    "package.json"
    "package-lock.json"
    "pnpm-lock.yaml"
    "yarn.lock"
    ".npmrc"
    ".nvmrc"
    ".node-version"
    "frontend/package.json"
    "frontend/package-lock.json"
  )

  local found=()
  for path in "${forbidden[@]}"; do
    if [[ -e "$path" ]]; then
      found+=("$path")
    fi
  done

  if (( ${#found[@]} > 0 )); then
    error "Node/NPM artifacts detected: ${found[*]}"
  else
    info "No Node or npm artifacts detected."
  fi
}

check_import_map() {
  local import_map_path="frontend/importmap.json"
  local static_map_path="frontend/static/importmap.json"

  if [[ ! -f "${import_map_path}" ]]; then
    error "frontend/importmap.json is missing"
    return
  fi

  python3 <<'PYTHON'
import json
import re
import sys
from pathlib import Path

import_map_path = Path("frontend/importmap.json")
static_map_path = Path("frontend/static/importmap.json")

errors = []
warnings = []

try:
    data = json.loads(import_map_path.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:  # noqa: PERF203
    errors.append(f"frontend/importmap.json is not valid JSON: {exc}")
    data = {"imports": {}}

imports = data.get("imports", {})
if not isinstance(imports, dict):
    errors.append("frontend/importmap.json: 'imports' must be an object")
    imports = {}

pin_regex = re.compile(r"@[0-9][^/]*")
for specifier, target in imports.items():
    if not isinstance(target, str):
        errors.append(f"Import target for '{specifier}' must be a string")
        continue
    if target.startswith(("http://", "https://")):
        if not target.startswith("https://"):
            errors.append(f"{specifier}: only https:// URLs are allowed ({target})")
        if "@latest" in target:
            errors.append(f"{specifier}: version must be pinned, '@latest' is not allowed ({target})")
        elif not pin_regex.search(target):
            errors.append(f"{specifier}: dependency must contain an explicit version (@x.y.z) ({target})")

if static_map_path.exists():
    try:
        static_data = json.loads(static_map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # noqa: PERF203
        errors.append(f"frontend/static/importmap.json is not valid JSON: {exc}")
        static_data = {"imports": {}}
    if isinstance(static_data.get("imports"), dict):
        missing = set(imports) - set(static_data["imports"].keys())
        if missing:
            warnings.append(
                "frontend/static/importmap.json is missing specifiers: "
                + ", ".join(sorted(missing))
            )
else:
    errors.append("frontend/static/importmap.json is missing")

if errors:
    for message in errors:
        print(f"ERROR:{message}", file=sys.stderr)
    sys.exit(1)

for message in warnings:
    print(f"WARN:{message}", file=sys.stderr)

PYTHON
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    status=1
  fi
}

check_forbidden_references() {
  if command -v rg >/dev/null 2>&1; then
    if rg -n "\\b(npm|yarn|pnpm)\\b" -- frontend >/dev/null 2>&1; then
      error "Detected legacy package manager references under frontend/."
    else
      info "No legacy package manager references found under frontend/."
    fi
  else
    info "ripgrep not available; skipped textual scan for legacy references."
  fi
}

check_forbidden_artifacts
check_import_map
check_forbidden_references

if [[ $status -ne 0 ]]; then
  exit $status
fi

echo "[supply-guard] All checks passed." >&2
