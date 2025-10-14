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

check_frontend_structure() {
  local required=(
    "frontend-static/index.html"
    "frontend-static/spotify.html"
    "frontend-static/downloads.html"
    "frontend-static/settings.html"
    "frontend-static/health.html"
    "frontend-static/assets/styles.css"
    "frontend-static/js/fetch-client.js"
  )

  local missing=()
  for path in "${required[@]}"; do
    if [[ ! -e "$path" ]]; then
      missing+=("$path")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    error "Frontend assets missing: ${missing[*]}"
  else
    info "Frontend static bundle detected."
  fi
}

check_forbidden_references() {
  if command -v rg >/dev/null 2>&1; then
    if rg -n "\\b(npm|yarn|pnpm)\\b" -- frontend-static >/dev/null 2>&1; then
      error "Detected legacy package manager references under frontend-static/."
    else
      info "No legacy package manager references found under frontend-static/."
    fi
  else
    info "ripgrep not available; skipped textual scan for legacy references."
  fi
}

check_forbidden_artifacts
check_frontend_structure
check_forbidden_references

if [[ $status -ne 0 ]]; then
  exit $status
fi

echo "[supply-guard] All checks passed." >&2
