#!/usr/bin/env bash
set -euo pipefail

: "${SUPPLY_GUARD_VERBOSE:=0}"
: "${SUPPLY_GUARD_TIMEOUT_SEC:=120}"
: "${SKIP_SUPPLY_GUARD:=0}"

DEFAULT_REGISTRY="https://registry.npmjs.org/"

MODE="STRICT"
MODE_REASON="default"
IS_CI=0

REQUIRED_NODE_VERSION=""
REQUIRED_NPM_VERSION=""

declare -i ERROR_COUNT=0
declare -i WARN_COUNT=0
declare -i INFO_COUNT=0
declare -i P0_COUNT=0
declare -i WARN_ONLY_COUNT=0
declare -i WARNABLE_TOTAL=0
declare -i EXIT_CODE=0
WARN_PRESENT=0

FAIL_NODE_DRIFT=1
FAIL_NPM_DRIFT=1
FAIL_NPM_INTEGRITY=1
FAIL_PY_HASH=1
FAIL_OFFREGISTRY=1

lower(){
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

trim(){
  local value="$1"
  printf '%s' "${value}" | tr -d '\r' | sed -e 's/^\s\+//' -e 's/\s\+$//'
}

normalize_registry(){
  local value="$1"
  value="$(trim "${value}")"
  value="${value%/}"
  if [ -z "${value}" ]; then
    echo ""
    return
  fi
  printf '%s/' "${value}"
}

is_truthy(){
  local raw="$(lower "${1:-}")"
  case "${raw}" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

emit_event(){
  local level="$1"
  local check="$2"
  local details="$3"
  local fix="${4:--}"
  printf '[supply-guard] %s | %s | %s | %s\n' "${level}" "${check}" "${details}" "${fix}"
  case "${level}" in
    ERROR)
      ERROR_COUNT=$((ERROR_COUNT + 1))
      EXIT_CODE=1
      ;;
    WARN)
      WARN_COUNT=$((WARN_COUNT + 1))
      WARN_PRESENT=1
      ;;
    INFO)
      INFO_COUNT=$((INFO_COUNT + 1))
      ;;
  esac
}

report_info(){
  emit_event "INFO" "$1" "$2" "${3:--}"
}

report_warn(){
  emit_event "WARN" "$1" "$2" "${3:--}"
}

report_error(){
  emit_event "ERROR" "$1" "$2" "${3:--}"
}

report_blocking(){
  P0_COUNT=$((P0_COUNT + 1))
  report_error "$1" "$2" "$3"
}

resolve_flag(){
  local name="$1"
  local raw="$2"
  local default_value="$3"
  if [ -z "${raw}" ]; then
    echo "${default_value}"
    return
  fi
  local normalized
  normalized="$(lower "${raw}")"
  case "${normalized}" in
    1|true|yes|on)
      echo 1
      ;;
    0|false|no|off)
      echo 0
      ;;
    *)
      report_warn "CONFIG" "Ungültiger Bool-Wert für ${name}: '${raw}', verwende Default ${default_value}" "Setze ${name}=0 oder ${name}=1"
      echo "${default_value}"
      ;;
  esac
}

report_warnable(){
  local kind="$1"
  local details="$2"
  local fix="${3:--}"
  local check="${kind}"
  local fail_flag=1

  case "${kind}" in
    node_drift)
      check="NODE_VERSION"
      fail_flag=${FAIL_NODE_DRIFT}
      ;;
    npm_drift)
      check="NPM_VERSION"
      fail_flag=${FAIL_NPM_DRIFT}
      ;;
    npm_integrity)
      check="NPM_INTEGRITY"
      fail_flag=${FAIL_NPM_INTEGRITY}
      ;;
    python_hash)
      check="PYTHON_HASH"
      fail_flag=${FAIL_PY_HASH}
      ;;
  esac

  WARNABLE_TOTAL=$((WARNABLE_TOTAL + 1))

  local severity="ERROR"
  local details_text="${details}"

  if [ "${MODE}" = "WARN" ] && [ "${fail_flag}" -eq 0 ]; then
    severity="WARN"
    WARN_ONLY_COUNT=$((WARN_ONLY_COUNT + 1))
    details_text="${details_text} (STRICT-Modus bricht ab.)"
  fi

  if [ "${severity}" = "ERROR" ]; then
    report_error "${check}" "${details_text}" "${fix}"
  else
    report_warn "${check}" "${details_text}" "${fix}"
  fi
}

run_with_timeout(){
  local secs="$1"
  shift
  local status
  if command -v timeout >/dev/null 2>&1; then
    if timeout --help 2>&1 | grep -q "--preserve-status"; then
      timeout --preserve-status "${secs}" "$@"
      status=$?
    else
      timeout "${secs}" "$@"
      status=$?
    fi
  else
    "$@"
    status=$?
  fi
  return "${status}"
}

has_any(){
  command -v "$1" >/dev/null 2>&1
}

determine_mode(){
  local mode_override="${SUPPLY_MODE:-}"
  local toolchain_setting="${TOOLCHAIN_STRICT:-}"

  MODE="STRICT"
  MODE_REASON="default"
  IS_CI=0

  if is_truthy "${CI:-}" || is_truthy "${GITHUB_ACTIONS:-}"; then
    IS_CI=1
  fi

  if [ "${IS_CI}" -eq 1 ]; then
    MODE="STRICT"
    MODE_REASON="CI erzwingt STRICT"
    if [ -n "${mode_override}" ] && [ "$(lower "${mode_override}")" = "warn" ]; then
      report_warn "MODE" "SUPPLY_MODE=WARN wird in CI ignoriert; STRICT erzwungen." "Entferne SUPPLY_MODE=WARN aus CI-Umgebungen"
    fi
    return
  fi

  if [ -n "${mode_override}" ]; then
    case "$(lower "${mode_override}")" in
      warn)
        MODE="WARN"
        MODE_REASON="SUPPLY_MODE=WARN"
        return
        ;;
      strict)
        MODE="STRICT"
        MODE_REASON="SUPPLY_MODE=STRICT"
        return
        ;;
      *)
        report_warn "MODE" "SUPPLY_MODE='${mode_override}' unbekannt, fallback STRICT." "Nutze SUPPLY_MODE=STRICT oder SUPPLY_MODE=WARN"
        ;;
    esac
  fi

  if [ -n "${toolchain_setting}" ]; then
    case "$(lower "${toolchain_setting}")" in
      0|false|no|off)
        MODE="WARN"
        MODE_REASON="TOOLCHAIN_STRICT=false"
        return
        ;;
      *)
        MODE="STRICT"
        MODE_REASON="TOOLCHAIN_STRICT=true"
        return
        ;;
    esac
  fi

  MODE="STRICT"
  MODE_REASON="Default STRICT"
}

init_fail_matrix(){
  local default_warnable=1
  if [ "${MODE}" = "WARN" ] && [ "${IS_CI}" -eq 0 ]; then
    default_warnable=0
  fi

  FAIL_NODE_DRIFT=$(resolve_flag "SUPPLY_FAIL_NODE_DRIFT" "${SUPPLY_FAIL_NODE_DRIFT:-${default_warnable}}" "${default_warnable}")
  FAIL_NPM_DRIFT=$(resolve_flag "SUPPLY_FAIL_NPM_DRIFT" "${SUPPLY_FAIL_NPM_DRIFT:-${default_warnable}}" "${default_warnable}")
  FAIL_NPM_INTEGRITY=$(resolve_flag "SUPPLY_FAIL_NPM_INTEGRITY" "${SUPPLY_FAIL_NPM_INTEGRITY:-${default_warnable}}" "${default_warnable}")
  FAIL_PY_HASH=$(resolve_flag "SUPPLY_FAIL_PY_HASH" "${SUPPLY_FAIL_PY_HASH:-${default_warnable}}" "${default_warnable}")

  local off_default=1
  FAIL_OFFREGISTRY=$(resolve_flag "SUPPLY_FAIL_OFFREGISTRY" "${SUPPLY_FAIL_OFFREGISTRY:-${off_default}}" "${off_default}")
  if [ "${FAIL_OFFREGISTRY}" -ne 1 ]; then
    FAIL_OFFREGISTRY=1
    report_warn "CONFIG" "SUPPLY_FAIL_OFFREGISTRY kann nicht deaktiviert werden; erzwinge Blockierung." "Entferne SUPPLY_FAIL_OFFREGISTRY Override"
  fi
}

ensure_registry_file(){
  local file="$1"
  local context="$2"
  if [ ! -f "${file}" ]; then
    report_error "REGISTRY" "${context}: .npmrc fehlt" "Lege ${file} mit registry=${DEFAULT_REGISTRY} an"
    return
  fi
  if ! grep -Eqs '^registry=https://registry\.npmjs\.org/?$' "${file}"; then
    report_error "REGISTRY" "${context}: Registry != ${DEFAULT_REGISTRY}" "Setze registry=${DEFAULT_REGISTRY} in ${file}"
  fi
  if grep -E 'registry=' "${file}" | grep -Ev '^registry=https://registry\.npmjs\.org/?$' >/dev/null 2>&1; then
    report_error "REGISTRY" "${context}: zusätzliche Registry-Einträge gefunden" "Entferne alternative Registries aus ${file}"
  fi
}

load_toolchain_manifest(){
  if [ -f .nvmrc ]; then
    REQUIRED_NODE_VERSION=$(trim "$(cat .nvmrc)")
    if [ -z "${REQUIRED_NODE_VERSION}" ]; then
      report_error "TOOLCHAIN" ".nvmrc ist leer" "Trage die gepinnte Node-Version in .nvmrc ein"
    fi
  else
    report_error "TOOLCHAIN" ".nvmrc fehlt" "Füge .nvmrc mit der geforderten Node-Version hinzu"
  fi

  local node_version_file=""
  if [ -f .node-version ]; then
    node_version_file=$(trim "$(cat .node-version)")
    if [ -z "${node_version_file}" ]; then
      report_error "TOOLCHAIN" ".node-version ist leer" "Trage die Node-Version in .node-version ein"
    fi
  else
    report_error "TOOLCHAIN" ".node-version fehlt" "Erzeuge .node-version mit derselben Version wie .nvmrc"
  fi

  if [ -n "${REQUIRED_NODE_VERSION}" ] && [ -n "${node_version_file}" ] && [ "${REQUIRED_NODE_VERSION}" != "${node_version_file}" ]; then
    report_error "TOOLCHAIN" ".nvmrc (${REQUIRED_NODE_VERSION}) != .node-version (${node_version_file})" "Gleiche .nvmrc und .node-version an"
  fi

  if [ -f frontend/.npm-version ]; then
    REQUIRED_NPM_VERSION=$(trim "$(cat frontend/.npm-version)")
    if [ -z "${REQUIRED_NPM_VERSION}" ]; then
      report_error "TOOLCHAIN" "frontend/.npm-version ist leer" "Trage die npm-Version ein"
    fi
  else
    report_error "TOOLCHAIN" "frontend/.npm-version fehlt" "Füge frontend/.npm-version mit der erwarteten npm-Version hinzu"
  fi
}

check_repo_registry(){
  ensure_registry_file .npmrc "Repo"
  if [ -d frontend ]; then
    ensure_registry_file frontend/.npmrc "frontend"
  fi
}

check_node(){
  if [ ! -d frontend ]; then
    report_info "NODE" "frontend/ nicht vorhanden – überspringe Node-Prüfungen" "-"
    return
  fi

  pushd frontend >/dev/null || return

  if ! has_any node; then
    report_error "NODE_TOOLCHAIN" "Node.js nicht gefunden" "Installiere Node $(printf '%s' "${REQUIRED_NODE_VERSION:-<siehe .nvmrc>}") via nvm"
    popd >/dev/null || true
    return
  fi

  local actual_node
  actual_node="$(node --version 2>/dev/null | sed 's/^v//')"
  if [ -n "${REQUIRED_NODE_VERSION}" ] && [ -n "${actual_node}" ] && [ "${actual_node}" != "${REQUIRED_NODE_VERSION}" ]; then
    local fix="nvm install ${REQUIRED_NODE_VERSION} && nvm use ${REQUIRED_NODE_VERSION}"
    report_warnable "node_drift" "Node.js ${actual_node} erkannt, erwartet ${REQUIRED_NODE_VERSION}" "${fix}"
  fi

  if ! has_any npm; then
    report_error "NODE_TOOLCHAIN" "npm nicht gefunden" "Installiere npm ${REQUIRED_NPM_VERSION:-<laut frontend/.npm-version>}"
  else
    local npm_version
    npm_version="$(npm --version 2>/dev/null | tail -n1 || true)"
    if [ -n "${REQUIRED_NPM_VERSION}" ] && [ -n "${npm_version}" ] && [ "${npm_version}" != "${REQUIRED_NPM_VERSION}" ]; then
      local fix="npm install -g npm@${REQUIRED_NPM_VERSION}"
      report_warnable "npm_drift" "npm ${npm_version} erkannt, erwartet ${REQUIRED_NPM_VERSION}" "${fix}"
    fi
  fi

  if [ ! -f package-lock.json ] && [ ! -f pnpm-lock.yaml ] && [ ! -f yarn.lock ]; then
    report_error "LOCKFILE" "Kein Lockfile im frontend/ gefunden" "Führe npm ci aus und committe package-lock.json"
  fi

  if [ -f package-lock.json ]; then
    local off_url=""
    if command -v jq >/dev/null 2>&1; then
      off_url="$(jq -r '..|.resolved? // empty' package-lock.json | grep -E '^https?://' | grep -Ev '^https?://registry\.npmjs\.org/' | head -n 1 || true)"
    else
      off_url="$(grep -E '"resolved":\s*"https?://[^" ]+' package-lock.json | grep -Ev 'https?://registry\.npmjs\.org/' | head -n 1 || true)"
    fi
    if [ -n "${off_url}" ]; then
      report_blocking "OFF_REGISTRY" "Lockfile nutzt Off-Registry URL ${off_url}" "Aktualisiere auf Pakete von ${DEFAULT_REGISTRY}"
    fi
  fi

  if has_any npm; then
    local npm_registry
    npm_registry="$(normalize_registry "$(npm config get registry 2>/dev/null || true)")"
    if [ -n "${npm_registry}" ] && [ "${npm_registry}" != "${DEFAULT_REGISTRY}" ]; then
      report_error "REGISTRY" "npm config registry=${npm_registry}, erwartet ${DEFAULT_REGISTRY}" "npm config set registry ${DEFAULT_REGISTRY}"
    fi
  fi

  if [ -f package-lock.json ]; then
    set +e
    run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" npm ci --dry-run --no-audit --no-fund >/dev/null 2>&1
    local status=$?
    set -e
    if [ "${status}" -eq 124 ]; then
      report_error "NPM_INTEGRITY" "npm ci --dry-run Timeout nach ${SUPPLY_GUARD_TIMEOUT_SEC}s" "Prüfe auf Blocker bei npm ci --dry-run"
    elif [ "${status}" -ne 0 ]; then
      local fix="npm ci && npm install --package-lock-only"
      report_warnable "npm_integrity" "npm ci --dry-run meldet Resolver/Integrity-Fehler (Exit ${status})" "${fix}"
    fi
  fi

  popd >/dev/null || true
}

collect_requirement_files(){
  local -n ref=$1
  while IFS= read -r -d '' path; do
    case "${path}" in
      ./frontend/*)
        continue
        ;;
    esac
    ref+=("${path#./}")
  done < <(find . -maxdepth 2 -type f -name 'requirements*.txt' -print0 2>/dev/null)
}

run_pip_install(){
  local pip_cmd="$1"
  shift
  if [ "${pip_cmd}" = "pip" ]; then
    run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" pip "$@"
  else
    # shellcheck disable=SC2086
    run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" ${pip_cmd} "$@"
  fi
}

check_python(){
  local py=""
  if has_any python3; then
    py="python3"
  elif has_any python; then
    py="python"
  fi

  local pip_cmd=""
  if has_any pip; then
    pip_cmd="pip"
  elif [ -n "${py}" ] && "${py}" -m pip --version >/dev/null 2>&1; then
    pip_cmd="${py} -m pip"
  fi

  local requirement_files=()
  collect_requirement_files requirement_files

  if [ "${#requirement_files[@]}" -eq 0 ]; then
    report_info "PYTHON" "Keine requirements*.txt gefunden – überspringe Python-Check" "-"
    return
  fi

  if [ -z "${pip_cmd}" ]; then
    report_warnable "python_hash" "pip nicht gefunden – Hash-Validierung nicht möglich" "Installiere pip (python -m ensurepip --upgrade)"
    return
  fi

  local file
  for file in "${requirement_files[@]}"; do
    if [ ! -f "${file}" ]; then
      continue
    fi
    if ! grep -Eq -- '--hash=' "${file}"; then
      report_warnable "python_hash" "${file} enthält keine --hash Einträge" "Regeneriere via pip-compile --generate-hashes > ${file}"
      continue
    fi
    set +e
    run_pip_install "${pip_cmd}" install --dry-run --require-hashes --no-deps -r "${file}" >/dev/null 2>&1
    local status=$?
    set -e
    if [ "${status}" -eq 124 ]; then
      report_error "PYTHON_HASH" "pip --require-hashes Timeout für ${file}" "Führe pip install --require-hashes -r ${file} lokal aus"
    elif [ "${status}" -ne 0 ]; then
      report_warnable "python_hash" "pip meldet Hash-/Resolver-Drift in ${file} (Exit ${status})" "Regeneriere ${file} via pip-compile --generate-hashes"
    else
      report_info "PYTHON_HASH" "Hashes für ${file} verifiziert" "-"
    fi
  done
}

check_go(){
  if [ ! -f go.mod ]; then
    return
  fi
  if ! has_any go; then
    report_error "GO" "go nicht gefunden" "Installiere Go und stelle PATH bereit"
    return
  fi
  set +e
  run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" go mod verify >/dev/null 2>&1
  local status=$?
  set -e
  if [ "${status}" -eq 124 ]; then
    report_error "GO" "go mod verify Timeout" "Führe go mod verify lokal für weitere Details aus"
  elif [ "${status}" -ne 0 ]; then
    report_error "GO" "go mod verify fehlgeschlagen" "Synchronisiere Module via go mod tidy"
  else
    report_info "GO" "go.mod erfolgreich verifiziert" "-"
  fi
}

check_rust(){
  if [ ! -f Cargo.toml ]; then
    return
  fi
  if ! has_any cargo; then
    report_error "RUST" "cargo nicht gefunden" "Installiere Rust/Cargo"
    return
  fi
  if [ ! -f Cargo.lock ]; then
    report_error "RUST" "Cargo.lock fehlt" "Erzeuge Cargo.lock via cargo generate-lockfile"
    return
  fi
  set +e
  run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" cargo generate-lockfile --locked >/dev/null 2>&1
  local status=$?
  set -e
  if [ "${status}" -eq 124 ]; then
    report_error "RUST" "cargo generate-lockfile Timeout" "Prüfe auf Lockfile-Konflikte"
  elif [ "${status}" -ne 0 ]; then
    report_error "RUST" "Cargo-Lock nicht reproduzierbar" "Führe cargo update --locked und committe das Ergebnis"
  else
    report_info "RUST" "Cargo.lock bestätigt" "-"
  fi
}

check_java_kotlin(){
  if [ -f build.gradle ] || [ -f build.gradle.kts ]; then
    if ! has_any gradle; then
      report_error "GRADLE" "gradle nicht gefunden" "Installiere Gradle"
      return
    fi
    if ! grep -Eqs "dependencyLocking" build.gradle*; then
      report_error "GRADLE" "dependencyLocking nicht aktiviert" "Aktiviere dependencyLocking in build.gradle"
    else
      report_info "GRADLE" "Gradle dependencyLocking vorhanden" "-"
    fi
    return
  fi

  if [ -f pom.xml ]; then
    if ! has_any mvn; then
      report_error "MAVEN" "mvn nicht gefunden" "Installiere Maven"
      return
    fi
    if ! grep -Eqs "<dependencyManagement>" pom.xml; then
      report_error "MAVEN" "dependencyManagement Abschnitt fehlt" "Füge <dependencyManagement> hinzu"
    else
      report_info "MAVEN" "dependencyManagement vorhanden" "-"
    fi
  fi
}

check_ruby(){
  if [ ! -f Gemfile ]; then
    return
  fi
  if ! has_any bundle; then
    report_error "BUNDLER" "bundler nicht gefunden" "Installiere Bundler"
    return
  fi
  if [ ! -f Gemfile.lock ]; then
    report_error "BUNDLER" "Gemfile.lock fehlt" "Führe bundle lock aus"
    return
  fi
  set +e
  run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" bundle check >/dev/null 2>&1
  local status=$?
  set -e
  if [ "${status}" -eq 124 ]; then
    report_error "BUNDLER" "bundle check Timeout" "Führe bundle check lokal für Details aus"
  elif [ "${status}" -ne 0 ]; then
    report_error "BUNDLER" "bundle check fehlgeschlagen" "Führe bundle install --deployment"
  else
    report_info "BUNDLER" "bundle check erfolgreich" "-"
  fi
}

check_php(){
  if [ ! -f composer.json ]; then
    return
  fi
  if ! has_any composer; then
    report_error "COMPOSER" "composer nicht gefunden" "Installiere Composer"
    return
  fi
  if [ ! -f composer.lock ]; then
    report_error "COMPOSER" "composer.lock fehlt" "Erzeuge composer.lock via composer install"
    return
  fi
  set +e
  run_with_timeout "${SUPPLY_GUARD_TIMEOUT_SEC}" composer validate --no-check-publish >/dev/null 2>&1
  local status=$?
  set -e
  if [ "${status}" -eq 124 ]; then
    report_error "COMPOSER" "composer validate Timeout" "Führe composer validate lokal aus"
  elif [ "${status}" -ne 0 ]; then
    report_error "COMPOSER" "composer validate fehlgeschlagen" "Führe composer update --lock"
  else
    report_info "COMPOSER" "composer validate erfolgreich" "-"
  fi
}

check_docker(){
  local dockerfiles
  dockerfiles=$(ls Dockerfile Dockerfile.* 2>/dev/null || true)
  if [ -z "${dockerfiles}" ]; then
    return
  fi

  if grep -Rqs "^FROM .*:latest" Dockerfile Dockerfile.* 2>/dev/null; then
    report_warn "DOCKER" "Docker FROM nutzt :latest" "Pinne eine konkrete Version oder Digest"
  fi

  if ! grep -Rqs "^FROM .*@" Dockerfile Dockerfile.* 2>/dev/null; then
    report_warn "DOCKER" "Docker FROM ohne Digest" "Nutze ein Image mit Digest (name@sha256:...)"
  else
    report_info "DOCKER" "Docker FROM nutzt Digest" "-"
  fi
}

print_summary(){
  local mode_note="${MODE}"
  if [ "${IS_CI}" -eq 1 ]; then
    mode_note="${mode_note} (CI enforced)"
  fi

  printf '[supply-guard] SUMMARY | MODE | %s | -\n' "${mode_note}"
  printf '[supply-guard] SUMMARY | ERROR_COUNT | %d | -\n' "${ERROR_COUNT}"
  printf '[supply-guard] SUMMARY | WARN_COUNT | %d | -\n' "${WARN_COUNT}"
  printf '[supply-guard] SUMMARY | INFO_COUNT | %d | -\n' "${INFO_COUNT}"
  printf '[supply-guard] SUMMARY | WARNABLE_TOTAL | %d | -\n' "${WARNABLE_TOTAL}"
  printf '[supply-guard] SUMMARY | WARN_ONLY | %d | Resolve vor Commit (Follow-up required)\n' "${WARN_ONLY_COUNT}"
  printf '[supply-guard] SUMMARY | P0_BLOCKS | %d | -\n' "${P0_COUNT}"
  printf '[supply-guard] SUMMARY | EXIT_STATUS | %d | -\n' "${EXIT_CODE}"

  if [ "${WARN_PRESENT}" -eq 1 ]; then
    printf '[supply-guard] WARN | SUMMARY | WARNINGS erkannt – Follow-up erforderlich | Behebe WARNs vor Commit/Push\n'
  fi
}

main(){
  if [ "${SKIP_SUPPLY_GUARD}" = "1" ]; then
    report_info "SKIP" "Supply-Guard via SKIP_SUPPLY_GUARD=1 deaktiviert" "-"
    exit 0
  fi

  determine_mode
  init_fail_matrix
  local mode_note="${MODE}"
  if [ "${IS_CI}" -eq 1 ]; then
    mode_note="${mode_note} (CI enforced)"
  fi
  report_info "MODE" "Supply-Guard Modus ${mode_note} (${MODE_REASON}) aktiv" "Setze SUPPLY_MODE=STRICT|WARN für Overrides"
  report_info "CONFIG" "Fail-Matrix: node=${FAIL_NODE_DRIFT}, npm=${FAIL_NPM_DRIFT}, npm_integrity=${FAIL_NPM_INTEGRITY}, python=${FAIL_PY_HASH}, off_registry=${FAIL_OFFREGISTRY}" "Überschreibe via SUPPLY_FAIL_*"

  report_info "INIT" "Start SUPPLY_GUARD_TIMEOUT_SEC=${SUPPLY_GUARD_TIMEOUT_SEC} verbose=${SUPPLY_GUARD_VERBOSE}" "-"

  load_toolchain_manifest
  check_repo_registry
  check_node
  check_python
  check_go
  check_rust
  check_java_kotlin
  check_ruby
  check_php
  check_docker

  print_summary

  exit "${EXIT_CODE}"
}

main "$@"
