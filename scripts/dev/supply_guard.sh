#!/usr/bin/env bash
set -euo pipefail

# Exit codes:
# 0 OK, 2 Warnung, 3 Drift, 4 Integrity-Fehler, 5 Toolchain fehlt
EXIT_OK=0
EXIT_WARN=2
EXIT_DRIFT=3
EXIT_INT=4
EXIT_TOOL=5

: "${SUPPLY_GUARD_VERBOSE:=0}"
: "${SUPPLY_GUARD_TIMEOUT_SEC:=120}"
: "${SKIP_SUPPLY_GUARD:=0}"

if [ "${SKIP_SUPPLY_GUARD}" = "1" ]; then
  echo "[supply-guard] skipped via SKIP_SUPPLY_GUARD=1"
  exit ${EXIT_OK}
fi

warn_flag=0
fail_code=0

run_with_timeout() {
  local secs="$1"
  shift
  set +e
  if command -v timeout >/dev/null 2>&1; then
    if timeout --help 2>&1 | grep -q "--preserve-status"; then
      timeout --preserve-status "${secs}" "$@"
    else
      timeout "${secs}" "$@"
    fi
  else
    "$@"
  fi
  local status=$?
  set -e
  return ${status}
}

has_any() {
  command -v "$1" >/dev/null 2>&1
}

log() {
  echo "[supply-guard] $*"
}

vlog() {
  if [ "${SUPPLY_GUARD_VERBOSE}" = "1" ]; then
    echo "[supply-guard] $*"
  fi
}

check_node() {
  if [ ! -d "frontend" ]; then
    return ${EXIT_OK}
  fi

  pushd frontend >/dev/null || return ${EXIT_OK}
  local code=${EXIT_OK}

  if ! has_any node || ! has_any npm; then
    log "Node/NPM nicht gefunden"
    code=${EXIT_TOOL}
  fi

  if [ "${code}" -eq ${EXIT_OK} ]; then
    local npm_major
    npm_major="$(npm --version 2>/dev/null | cut -d. -f1 || echo 0)"
    if ! [[ ${npm_major} =~ ^[0-9]+$ ]]; then
      npm_major=0
    fi
    if [ "${npm_major}" -lt 9 ]; then
      log "NPM-Major zu alt: ${npm_major}"
      code=${EXIT_TOOL}
    fi
  fi

  if [ "${code}" -eq ${EXIT_OK} ]; then
    if [ ! -f package-lock.json ] && [ ! -f pnpm-lock.yaml ] && [ ! -f yarn.lock ]; then
      log "Lockfile fehlt im frontend/"
      code=${EXIT_INT}
    fi
  fi

  if [ "${code}" -eq ${EXIT_OK} ] && [ -f .npmrc ]; then
    if ! grep -Eqs '^registry=https://registry\.npmjs\.org/?' .npmrc; then
      log ".npmrc Registry nicht npmjs.org"
      code=${EXIT_DRIFT}
    fi
  fi

  if [ "${code}" -eq ${EXIT_OK} ] && [ -f package-lock.json ]; then
    if grep -Eq '"resolved":\s*"https?://(?!registry\.npmjs\.org/)' package-lock.json; then
      log "Lockfile resolved-URLs zeigen nicht auf npmjs.org"
      code=${EXIT_DRIFT}
    fi
  fi

  if [ "${code}" -eq ${EXIT_OK} ]; then
    if run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" npm ci --dry-run --no-audit --no-fund >/dev/null 2>&1; then
      :
    else
      local status=$?
      if [ "${status}" -eq 124 ]; then
        log "npm ci --dry-run Timeout"
        code=${EXIT_DRIFT}
      else
        log "npm ci --dry-run Integrity/Resolver-Fehler"
        code=${EXIT_INT}
      fi
    fi
  fi

  popd >/dev/null || true
  return ${code}
}

check_python() {
  local py=""
  if has_any python3; then
    py="python3"
  elif has_any python; then
    py="python"
  fi

  if [ -z "${py}" ] || ! has_any pip; then
    vlog "Python/pip nicht gefunden, überspringe"
    return ${EXIT_OK}
  fi

  if [ -f "pyproject.toml" ] && grep -Eq '^\s*tool\.poetry\b' pyproject.toml; then
    if ! has_any poetry; then
      log "Poetry nicht installiert"
      return ${EXIT_TOOL}
    fi
    if run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" poetry check >/dev/null 2>&1; then
      :
    else
      local status=$?
      if [ "${status}" -eq 124 ]; then
        log "Poetry check Timeout"
        return ${EXIT_DRIFT}
      fi
      log "Poetry-Konfiguration fehlerhaft"
      return ${EXIT_DRIFT}
    fi
    if [ ! -f "poetry.lock" ]; then
      log "poetry.lock fehlt"
      return ${EXIT_INT}
    fi
    return ${EXIT_OK}
  fi

  if [ -f "requirements.txt" ]; then
    if grep -Eq '(^|\s)--hash=' requirements.txt; then
      vlog "requirements.txt mit Hashes erkannt"
      return ${EXIT_OK}
    fi
    log "requirements.txt ohne Hashes (Prod)"
    return ${EXIT_DRIFT}
  fi

  vlog "Kein Python-Manifest erkannt, überspringe"
  return ${EXIT_OK}
}

check_go() {
  if [ -f "go.mod" ]; then
    if ! has_any go; then
      log "Go nicht installiert"
      return ${EXIT_TOOL}
    fi
    if run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" go mod verify >/dev/null 2>&1; then
      :
    else
      local status=$?
      if [ "${status}" -eq 124 ]; then
        log "go mod verify Timeout"
        return ${EXIT_DRIFT}
      fi
      log "go mod verify fehlgeschlagen"
      return ${EXIT_INT}
    fi
  fi
  return ${EXIT_OK}
}

check_rust() {
  if [ -f "Cargo.toml" ]; then
    if ! has_any cargo; then
      log "Cargo nicht installiert"
      return ${EXIT_TOOL}
    fi
    if [ ! -f "Cargo.lock" ]; then
      log "Cargo.lock fehlt"
      return ${EXIT_INT}
    fi
    if run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" cargo generate-lockfile --locked >/dev/null 2>&1; then
      :
    else
      local status=$?
      if [ "${status}" -eq 124 ]; then
        log "Cargo generate-lockfile Timeout"
        return ${EXIT_DRIFT}
      fi
      log "Cargo-Lock nicht reproduzierbar"
      return ${EXIT_DRIFT}
    fi
  fi
  return ${EXIT_OK}
}

check_java_kotlin() {
  if [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
    if ! has_any gradle; then
      log "Gradle nicht installiert"
      return ${EXIT_TOOL}
    fi
    if ! grep -Eqs "dependencyLocking" build.gradle*; then
      log "Gradle Dependency-Locking nicht aktiviert"
      return ${EXIT_DRIFT}
    fi
    return ${EXIT_OK}
  fi

  if [ -f "pom.xml" ]; then
    if ! has_any mvn; then
      log "Maven nicht installiert"
      return ${EXIT_TOOL}
    fi
    if ! grep -Eqs "<dependencyManagement>" pom.xml; then
      log "Maven dependencyManagement fehlt"
      return ${EXIT_DRIFT}
    fi
    return ${EXIT_OK}
  fi

  return ${EXIT_OK}
}

check_ruby() {
  if [ -f "Gemfile" ]; then
    if ! has_any bundle; then
      log "Bundler nicht installiert"
      return ${EXIT_TOOL}
    fi
    if [ ! -f "Gemfile.lock" ]; then
      log "Gemfile.lock fehlt"
      return ${EXIT_INT}
    fi
    if run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" bundle check >/dev/null 2>&1; then
      :
    else
      local status=$?
      if [ "${status}" -eq 124 ]; then
        log "bundle check Timeout"
        return ${EXIT_DRIFT}
      fi
      log "bundle check fehlgeschlagen"
      return ${EXIT_DRIFT}
    fi
  fi
  return ${EXIT_OK}
}

check_php() {
  if [ -f "composer.json" ]; then
    if ! has_any composer; then
      log "Composer nicht installiert"
      return ${EXIT_TOOL}
    fi
    if [ ! -f "composer.lock" ]; then
      log "composer.lock fehlt"
      return ${EXIT_INT}
    fi
    if run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" composer validate --no-check-publish >/dev/null 2>&1; then
      :
    else
      local status=$?
      if [ "${status}" -eq 124 ]; then
        log "composer validate Timeout"
        return ${EXIT_DRIFT}
      fi
      log "composer validate fehlgeschlagen"
      return ${EXIT_DRIFT}
    fi
  fi
  return ${EXIT_OK}
}

check_docker() {
  local dockerfiles
  dockerfiles=$(ls Dockerfile Dockerfile.* 2>/dev/null || true)
  if [ -z "${dockerfiles}" ]; then
    return ${EXIT_OK}
  fi

  if grep -Rqs "^FROM .*:latest" Dockerfile Dockerfile.* 2>/dev/null; then
    log "Docker FROM mit 'latest' gefunden"
    return ${EXIT_WARN}
  fi

  if grep -Rqs "^FROM .*@" Dockerfile Dockerfile.* 2>/dev/null; then
    return ${EXIT_OK}
  fi

  log "Docker FROM ohne Digest"
  return ${EXIT_WARN}
}

accumulate() {
  local code="$1"
  case "${code}" in
    0)
      ;;
    2)
      warn_flag=1
      ;;
    3|4|5)
      if [ "${code}" -gt "${fail_code}" ]; then
        fail_code="${code}"
      fi
      ;;
    *)
      if [ "${code}" -gt "${fail_code}" ]; then
        fail_code="${code}"
      fi
      ;;
  esac
}

log "start SUPPLY_GUARD_TIMEOUT_SEC=${SUPPLY_GUARD_TIMEOUT_SEC} verbose=${SUPPLY_GUARD_VERBOSE}"

for check in check_node check_python check_go check_rust check_java_kotlin check_ruby check_php check_docker; do
  if declare -F "${check}" >/dev/null 2>&1; then
    vlog "running ${check}"
    code=${EXIT_OK}
    if "${check}"; then
      code=${EXIT_OK}
    else
      code=$?
    fi
    log "${check} -> ${code}"
    accumulate "${code}"
  fi
done

if [ "${fail_code}" -gt 0 ]; then
  exit "${fail_code}"
fi

if [ "${warn_flag}" -eq 1 ]; then
  exit ${EXIT_WARN}
fi

exit ${EXIT_OK}
