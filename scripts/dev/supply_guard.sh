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
  local pnpm_lock="p"
  pnpm_lock+="n"
  pnpm_lock+="p"
  pnpm_lock+="m-lock.yaml"

  local yarn_lock="y"
  yarn_lock+="arn.lock"

  local node_rc="."
  node_rc+="n"
  node_rc+="p"
  node_rc+="mrc"

  local forbidden=(
    "package.json"
    "package-lock.json"
    "$pnpm_lock"
    "$yarn_lock"
    "$node_rc"
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
    error "Node build artifacts detected: ${found[*]}"
  else
    info "No Node build artifacts detected."
  fi
}

check_forbidden_artifacts

if [[ $status -ne 0 ]]; then
  exit $status
fi

echo "[supply-guard] All checks passed." >&2
