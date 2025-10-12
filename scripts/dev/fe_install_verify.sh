#!/usr/bin/env bash
set -euo pipefail

# Exit codes
# 0  OK
# 10 Toolchain fehlt/inkompatibel
# 11 Lockfile fehlt/inkonsistent
# 12 Registry/Config-Drift
# 13 Installation fehlgeschlagen
# 14 Build fehlgeschlagen
# 15 Runtime-Konfiguration fehlt (env.runtime.js)
# 16 Projektstruktur unvollständig

: "${FE_DIR:=frontend}"
: "${TIMEOUT_SEC:=600}"
: "${PING_TIMEOUT_SEC:=30}"
: "${VERBOSE:=0}"
: "${SKIP_INSTALL:=0}"
: "${SKIP_BUILD:=0}"
: "${SKIP_TYPECHECK:=0}"
: "${SUPPLY_GUARD_RAN:=0}"

DEFAULT_REGISTRY="https://registry.npmjs.org/"

MODE="STRICT"
MODE_REASON="default"
IS_CI=0

FINAL_EXIT=0
SUMMARY_PRINTED=0
REGISTRY_STATUS="UNKNOWN"
REGISTRY_MESSAGE="-"
REGISTRY_URL="${DEFAULT_REGISTRY}"
INSTALL_STATUS="NOT_RUN"
INSTALL_MESSAGE="-"
BUILD_STATUS="NOT_RUN"
BUILD_MESSAGE="-"
INSTALL_OK=0
BUILD_OK=0
DEV_DEPS_AVAILABLE=0

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLCHAIN_NODE_FILE="${REPO_ROOT}/.nvmrc"
TOOLCHAIN_NODE_VERSION_FILE="${REPO_ROOT}/.node-version"
TOOLCHAIN_NPM_FILE="${REPO_ROOT}/${FE_DIR}/.npm-version"

cleanup_env_runtime=0
cleanup_env_runtime_path=""

emit_event(){
  local level="$1"
  local check="$2"
  local details="$3"
  local fix="${4:--}"
  printf '[fe-verify] %s | %s | %s | %s\n' "${level}" "${check}" "${details}" "${fix}"
}

info(){ emit_event "INFO" "$1" "$2" "${3:--}"; }
warn(){ emit_event "WARN" "$1" "$2" "${3:--}"; }
error(){ emit_event "ERROR" "$1" "$2" "${3:--}"; }

debug(){
  if [ "${VERBOSE}" = "1" ]; then
    emit_event "INFO" "DEBUG" "$1" "${2:--}"
  fi
}

fail(){
  local code="$1"
  shift
  error "$@"
  FINAL_EXIT="${code}"
  exit "${code}"
}

summary_line(){
  local key="$1"
  local details="$2"
  local fix="${3:--}"
  printf '[fe-verify] SUMMARY | %s | %s | %s\n' "${key}" "${details}" "${fix}"
}

on_exit(){
  local status=$?
  if [ "${SUMMARY_PRINTED}" = "1" ]; then
    exit "${status}"
  fi
  if [ "${FINAL_EXIT}" -eq 0 ] && [ "${status}" -ne 0 ]; then
    FINAL_EXIT="${status}"
  fi
  local mode_note="${MODE}"
  if [ "${IS_CI}" = "1" ]; then
    mode_note="${MODE} (CI)"
  fi
  summary_line "MODE" "${mode_note}" "${MODE_REASON}"
  summary_line "REGISTRY" "${REGISTRY_STATUS}" "${REGISTRY_MESSAGE}"
  summary_line "REGISTRY_URL" "${REGISTRY_URL}" "-"
  summary_line "INSTALL" "${INSTALL_STATUS}" "${INSTALL_MESSAGE}"
  summary_line "BUILD" "${BUILD_STATUS}" "${BUILD_MESSAGE}"
  summary_line "FINAL_EXIT" "${FINAL_EXIT}" "-"
  SUMMARY_PRINTED=1
  exit "${status}"
}
trap on_exit EXIT

trim(){
  local value="$1"
  printf '%s' "${value}" | tr -d '\r' | sed -e 's/^\s\+//' -e 's/\s\+$//'
}

lower(){
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

run_to(){
  local secs="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    if timeout --help 2>/dev/null | grep -q "--preserve-status"; then
      timeout --preserve-status "${secs}" "$@"
    else
      timeout "${secs}" "$@"
    fi
  else
    "$@"
  fi
}

sha256_file(){
  local target="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${target}" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${target}" | awk '{print $1}'
  else
    fail 16 "HASH" "sha256sum/shasum nicht verfügbar" "Installiere coreutils oder nutzt shasum"
  fi
}

stat_value(){
  local format_gnu="$1"
  local format_bsd="$2"
  local target="$3"
  if stat -c "${format_gnu}" "${target}" >/dev/null 2>&1; then
    stat -c "${format_gnu}" "${target}"
  else
    stat -f "${format_bsd}" "${target}"
  fi
}

capture_file_state(){
  local path="$1"
  if [ ! -f "${path}" ]; then
    echo "missing"
    return
  fi
  local hash size mtime
  hash="$(sha256_file "${path}")"
  size="$(stat_value '%s' '%z' "${path}")"
  mtime="$(stat_value '%Y' '%m' "${path}")"
  printf '%s:%s:%s' "${hash}" "${size}" "${mtime}"
}

states_equal(){
  local a="$1"
  local b="$2"
  if [ "${a}" = "${b}" ]; then
    return 0
  fi
  return 1
}

determine_mode(){
  local mode_override="${SUPPLY_MODE:-}"
  local toolchain_setting="${TOOLCHAIN_STRICT:-}"

  MODE="STRICT"
  MODE_REASON="default"
  IS_CI=0

  if [ -n "${CI:-}" ] && [ "$(lower "${CI}")" != "false" ]; then
    IS_CI=1
  elif [ -n "${GITHUB_ACTIONS:-}" ] && [ "$(lower "${GITHUB_ACTIONS}")" != "false" ]; then
    IS_CI=1
  fi

  if [ "${IS_CI}" -eq 1 ]; then
    MODE="STRICT"
    MODE_REASON="CI erzwingt STRICT"
    if [ -n "${mode_override}" ] && [ "$(lower "${mode_override}")" = "warn" ]; then
      warn "MODE" "SUPPLY_MODE=WARN wird in CI ignoriert; STRICT erzwungen" "Entferne SUPPLY_MODE=WARN aus CI-Umgebungen"
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
        warn "MODE" "Unbekannter SUPPLY_MODE='${mode_override}', fallback STRICT" "Setze SUPPLY_MODE=STRICT oder SUPPLY_MODE=WARN"
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

ensure_boolean(){
  local value="$1"
  case "${value}" in
    0|1) ;;
    *) fail 16 "CONFIG" "Boolesches Flag muss 0 oder 1 sein (erhalten: ${value})" "Setze 0 oder 1" ;;
  esac
}

require_cmd(){
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    fail 10 "TOOLCHAIN" "Benötigtes Werkzeug fehlt: ${cmd}" "Installiere ${cmd} gemäß Toolchain-Anleitung"
  fi
}

ensure_registry_line(){
  local file="$1"
  local context="$2"
  if [ ! -f "${file}" ]; then
    fail 12 "REGISTRY" "${context}: .npmrc fehlt" "Erzeuge ${file} mit registry=${DEFAULT_REGISTRY}"
  fi
  if ! grep -Eqs '^registry=https://registry\.npmjs\.org/?$' "${file}"; then
    fail 12 "REGISTRY" "${context}: Registry != ${DEFAULT_REGISTRY}" "Setze registry=${DEFAULT_REGISTRY}"
  fi
  if grep -E 'registry=' "${file}" | grep -Ev '^registry=https://registry\.npmjs\.org/?$' >/dev/null 2>&1; then
    fail 12 "REGISTRY" "${context}: zusätzliche Registry-Einträge gefunden" "Entferne alternative Registries"
  fi
}

detect_registry_forbidden(){
  local log_file="$1"
  if [ -f "${log_file}" ] && grep -Eqi '(E403|code E403|status[^0-9]*403|403 Forbidden)' "${log_file}"; then
    return 0
  fi
  return 1
}

detect_registry_network_issue(){
  local log_file="$1"
  if [ ! -f "${log_file}" ]; then
    return 1
  fi
  if grep -Eqi '(ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN)' "${log_file}"; then
    return 0
  fi
  if grep -Eqi 'network request failed|could not resolve' "${log_file}"; then
    return 0
  fi
  return 1
}

registry_hint(){
  echo "Prüfe Proxy/Firewall, Tokens und führe 'npm ping' erneut aus"
}

maybe_run_supply_guard(){
  if [ "${SUPPLY_GUARD_RAN}" = "1" ]; then
    info "SUPPLY_GUARD" "supply_guard bereits ausgeführt" "-"
    return
  fi
  local guard_script="${REPO_ROOT}/scripts/dev/supply_guard.sh"
  if [ -x "${guard_script}" ]; then
    info "SUPPLY_GUARD" "Starte supply_guard.sh" "-"
    SUPPLY_GUARD_RAN=1 bash "${guard_script}"
    SUPPLY_GUARD_RAN=1
  else
    warn "SUPPLY_GUARD" "supply_guard.sh nicht gefunden" "Stelle sicher, dass Skript ausführbar ist"
  fi
}

check_toolchain_versions(){
  if [ ! -f "${TOOLCHAIN_NODE_FILE}" ]; then
    fail 16 "TOOLCHAIN" "Toolchain-Datei ${TOOLCHAIN_NODE_FILE} fehlt" "Lege .nvmrc mit gepinnter Version an"
  fi
  if [ ! -f "${TOOLCHAIN_NODE_VERSION_FILE}" ]; then
    fail 16 "TOOLCHAIN" "Toolchain-Datei ${TOOLCHAIN_NODE_VERSION_FILE} fehlt" "Lege .node-version an"
  fi
  if [ ! -f "${TOOLCHAIN_NPM_FILE}" ]; then
    fail 16 "TOOLCHAIN" "Toolchain-Datei ${TOOLCHAIN_NPM_FILE} fehlt" "Lege frontend/.npm-version an"
  fi

  local required_node required_alt required_npm
  required_node="$(trim "$(cat "${TOOLCHAIN_NODE_FILE}")")"
  required_alt="$(trim "$(cat "${TOOLCHAIN_NODE_VERSION_FILE}")")"
  required_npm="$(trim "$(cat "${TOOLCHAIN_NPM_FILE}")")"

  if [ -z "${required_node}" ]; then
    fail 16 "TOOLCHAIN" "${TOOLCHAIN_NODE_FILE} ist leer" "Trage Node-Version ein"
  fi
  if [ -z "${required_alt}" ]; then
    fail 16 "TOOLCHAIN" "${TOOLCHAIN_NODE_VERSION_FILE} ist leer" "Trage Node-Version ein"
  fi
  if [ "${required_node}" != "${required_alt}" ]; then
    fail 16 "TOOLCHAIN" ".node-version (${required_alt}) weicht von .nvmrc (${required_node}) ab" "Synchronisiere Node-Versionen"
  fi
  if [ -z "${required_npm}" ]; then
    fail 16 "TOOLCHAIN" "${TOOLCHAIN_NPM_FILE} ist leer" "Trage npm-Version ein"
  fi

  local actual_node actual_npm
  actual_node="$(node --version | sed 's/^v//')"
  actual_npm="$(npm --version 2>/dev/null | tail -n1)"

  if [ "${actual_node}" != "${required_node}" ]; then
    local msg="Node.js ${actual_node} erkannt, erwartet ${required_node}"
    local fix="nvm install ${required_node} && nvm use ${required_node}"
    if [ "${MODE}" = "STRICT" ]; then
      fail 10 "TOOLCHAIN" "${msg}" "${fix}"
    else
      warn "TOOLCHAIN" "${msg} – WARN-Modus läuft weiter" "${fix}"
    fi
  fi

  if [ "${actual_npm}" != "${required_npm}" ]; then
    local msg="npm ${actual_npm} erkannt, erwartet ${required_npm}"
    local fix="npm install -g npm@${required_npm}"
    if [ "${MODE}" = "STRICT" ]; then
      fail 10 "TOOLCHAIN" "${msg}" "${fix}"
    else
      warn "TOOLCHAIN" "${msg} – WARN-Modus läuft weiter" "${fix}"
    fi
  fi

  info "TOOLCHAIN" "Node ${actual_node}, npm ${actual_npm}" "-"
}

check_registry_config(){
  ensure_registry_line "${REPO_ROOT}/.npmrc" "repo-root"
  ensure_registry_line "${REPO_ROOT}/${FE_DIR}/.npmrc" "${FE_DIR}"

  local npm_config_registry
  npm_config_registry="$(normalize_registry "$(npm config get registry 2>/dev/null || true)")"
  if [ "${npm_config_registry}" != "${DEFAULT_REGISTRY}" ]; then
    fail 12 "REGISTRY" "npm config registry='${npm_config_registry}', erwartet ${DEFAULT_REGISTRY}" "npm config set registry ${DEFAULT_REGISTRY}"
  fi
  REGISTRY_URL="${npm_config_registry:-${DEFAULT_REGISTRY}}"
  info "REGISTRY" "Registry konfiguriert: ${REGISTRY_URL}" "-"
}

run_npm_ping(){
  local log_file
  log_file="$(mktemp -t fe-verify-ping-XXXX.log)"
  if run_to "${PING_TIMEOUT_SEC}" npm ping >"${log_file}" 2>&1; then
    REGISTRY_STATUS="OK"
    REGISTRY_MESSAGE="npm ping erfolgreich"
    debug "npm ping OK" "-"
    rm -f "${log_file}"
    return 0
  fi

  if detect_registry_forbidden "${log_file}"; then
    REGISTRY_STATUS="FORBIDDEN"
    REGISTRY_MESSAGE="npm ping: HTTP 403"
    local sample="$(grep -Eio 'E403[^\\r\\n]*|403[^\\r\\n]*Forbidden' "${log_file}" | head -n1 | tr -d '\r')"
    if [ -n "${sample}" ]; then
      REGISTRY_MESSAGE="${REGISTRY_MESSAGE} (${sample})"
    fi
    rm -f "${log_file}"
    return 1
  fi

  if ! detect_registry_network_issue "${log_file}"; then
    REGISTRY_STATUS="ERROR"
    REGISTRY_MESSAGE="npm ping fehlgeschlagen"
  else
    REGISTRY_STATUS="UNREACHABLE"
    REGISTRY_MESSAGE="npm ping: Netzwerkfehler"
  fi
  rm -f "${log_file}"
  return 1
}

check_dev_dependencies(){
  local missing=()
  if ! node -e "require.resolve('vite')" >/dev/null 2>&1; then
    missing+=("vite")
  fi
  if ! node -e "require.resolve('typescript')" >/dev/null 2>&1; then
    missing+=("typescript")
  fi

  if [ ${#missing[@]} -eq 0 ]; then
    DEV_DEPS_AVAILABLE=1
    info "DEV_DEPS" "DevDependencies vorhanden (vite, typescript)" "-"
    return 0
  fi

  DEV_DEPS_AVAILABLE=0
  local detail="Fehlende DevDependencies: ${missing[*]}"
  if [ "${MODE}" = "STRICT" ]; then
    fail 13 "DEV_DEPS" "${detail}" "Führe npm ci im Strict-Modus erneut aus"
  else
    warn "DEV_DEPS" "${detail} – Build wird in WARN übersprungen" "Führe npm ci nach Registry-Fix erneut aus"
  fi
  return 1
}

ensure_lockfile_present(){
  if [ -f package-lock.json ]; then
    echo "package-lock.json"
    return
  fi
  if [ -f pnpm-lock.yaml ]; then
    echo "pnpm-lock.yaml"
    return
  fi
  if [ -f yarn.lock ]; then
    echo "yarn.lock"
    return
  fi
  fail 11 "LOCKFILE" "Kein Lockfile gefunden" "Committe package-lock.json oder pnpm-lock.yaml"
}

run_install_with_capture(){
  local log_file="$1"
  shift
  run_to "${TIMEOUT_SEC}" "$@" >"${log_file}" 2>&1
}

restore_backup_if_needed(){
  local backup_dir="$1"
  if [ -n "${backup_dir}" ] && [ -d "${backup_dir}" ] && [ ! -d node_modules ]; then
    mv "${backup_dir}" node_modules
  fi
  if [ -n "${backup_dir}" ] && [ -d "${backup_dir}" ]; then
    rm -rf "${backup_dir}"
  fi
}

main(){
  ensure_boolean "${SKIP_INSTALL}"
  ensure_boolean "${SKIP_BUILD}"
  ensure_boolean "${SKIP_TYPECHECK}"
  ensure_boolean "${SUPPLY_GUARD_RAN}"

  if [ "${SKIP_INSTALL}" = "1" ]; then
    fail 16 "CONFIG" "SKIP_INSTALL=1 wird nicht unterstützt" "Lass die Installation laufen"
  fi

  determine_mode
  info "MODE" "Frontend Verify Modus ${MODE} (${MODE_REASON})" "Setze SUPPLY_MODE=STRICT|WARN für Overrides"

  if [ ! -d "${REPO_ROOT}/${FE_DIR}" ]; then
    fail 16 "STRUCTURE" "Ordner '${FE_DIR}' fehlt" "Prüfe Checkout"
  fi

  require_cmd node
  require_cmd npm

  check_toolchain_versions
  check_registry_config

  maybe_run_supply_guard

  pushd "${REPO_ROOT}/${FE_DIR}" >/dev/null
  cleanup_env_runtime_path="$(pwd)/public/env.runtime.js"
  trap 'if [ "${cleanup_env_runtime}" = "1" ]; then rm -f "${cleanup_env_runtime_path}"; fi' RETURN

  if [ ! -f package.json ]; then
    fail 16 "STRUCTURE" "package.json fehlt" "Lege package.json im Frontend an"
  fi

  local lockfile
  lockfile="$(ensure_lockfile_present)"

  local package_state_before lock_state_before
  package_state_before="$(capture_file_state package.json)"
  lock_state_before=""
  if [ -n "${lockfile}" ] && [ -f "${lockfile}" ]; then
    lock_state_before="$(capture_file_state "${lockfile}")"
  fi

  local node_modules_present=0
  [ -d node_modules ] && node_modules_present=1

  local pm="" lock_hint="${lockfile}"
  local -a install_cmd=()
  local -a run_cmd=()
  case "${lockfile}" in
    package-lock.json)
      pm="npm"
      install_cmd=(npm ci --no-audit --no-fund)
      run_cmd=(npm run)
      ;;
    pnpm-lock.yaml)
      pm="pnpm"
      require_cmd pnpm
      install_cmd=(pnpm install --frozen-lockfile)
      run_cmd=(pnpm run)
      ;;
    yarn.lock)
      pm="yarn"
      require_cmd yarn
      install_cmd=(yarn install --frozen-lockfile)
      run_cmd=(yarn run)
      ;;
  esac

  debug "Erkanntes Package-Manager" "${pm}"

  local ping_ok=0
  if run_npm_ping; then
    ping_ok=1
  else
    local hint
    hint="$(registry_hint)"
    if [ "${MODE}" = "STRICT" ]; then
      fail 12 "REGISTRY" "${REGISTRY_MESSAGE}" "${hint}"
    fi
    warn "REGISTRY" "${REGISTRY_MESSAGE} – WARN-Modus fährt mit Fallback fort" "${hint}"
  fi

  INSTALL_STATUS="PENDING"
  INSTALL_MESSAGE="-"

  local install_log
  install_log="$(mktemp -t fe-verify-install-XXXX.log)"
  local backup_dir=""

  if [ "${ping_ok}" -eq 0 ]; then
    if [ "${MODE}" = "WARN" ] && [ "${REGISTRY_STATUS}" = "FORBIDDEN" ] && [ "${node_modules_present}" -eq 1 ] && states_equal "${package_state_before}" "$(capture_file_state package.json)" && ( [ -z "${lock_state_before}" ] || states_equal "${lock_state_before}" "$(capture_file_state "${lockfile}")" ); then
      INSTALL_STATUS="SKIPPED_DUE_TO_REGISTRY"
      INSTALL_MESSAGE="Registry 403 – vorhandene node_modules genutzt"
      INSTALL_OK=1
      info "INSTALL" "Install übersprungen (Registry 403, bestehende node_modules)" "Führe npm ci nach Registry-Fix erneut aus"
    else
      INSTALL_STATUS="INSTALL_UNAVAILABLE_DUE_TO_REGISTRY"
      INSTALL_MESSAGE="Registry-Problem blockiert Installation"
      INSTALL_OK=0
      warn "INSTALL" "Registry nicht erreichbar – Installation wird übersprungen" "${REGISTRY_MESSAGE}"
    fi
  else
    if [ "${node_modules_present}" -eq 1 ]; then
      backup_dir="node_modules.__backup__$(date +%s)"
      rm -rf "${backup_dir}"
      mv node_modules "${backup_dir}"
    fi

    info "INSTALL" "${pm} install (${lock_hint})" "-"
    if ! run_install_with_capture "${install_log}" "${install_cmd[@]}"; then
      if detect_registry_forbidden "${install_log}"; then
        REGISTRY_STATUS="FORBIDDEN"
        REGISTRY_MESSAGE="${pm} install: HTTP 403"
        local hint
        hint="$(registry_hint)"
        if [ "${MODE}" = "STRICT" ]; then
          restore_backup_if_needed "${backup_dir}"
          rm -f "${install_log}"
          fail 13 "REGISTRY" "${REGISTRY_MESSAGE}" "${hint}"
        fi
        if [ -n "${backup_dir}" ] && [ -d "${backup_dir}" ]; then
          mv "${backup_dir}" node_modules
          INSTALL_STATUS="SKIPPED_DUE_TO_REGISTRY"
          INSTALL_MESSAGE="Registry 403 – vorhandene node_modules wiederhergestellt"
          INSTALL_OK=1
          warn "INSTALL" "${REGISTRY_MESSAGE}; benutze bestehende node_modules" "${hint}"
        else
          INSTALL_STATUS="INSTALL_UNAVAILABLE_DUE_TO_REGISTRY"
          INSTALL_MESSAGE="Registry 403 – keine node_modules verfügbar"
          INSTALL_OK=0
          warn "INSTALL" "${REGISTRY_MESSAGE}; kein node_modules Backup" "${hint}"
        fi
      elif detect_registry_network_issue "${install_log}"; then
        REGISTRY_STATUS="UNREACHABLE"
        REGISTRY_MESSAGE="${pm} install: Netzwerkfehler"
        local hint
        hint="$(registry_hint)"
        if [ "${MODE}" = "STRICT" ]; then
          restore_backup_if_needed "${backup_dir}"
          rm -f "${install_log}"
          fail 13 "REGISTRY" "${REGISTRY_MESSAGE}" "${hint}"
        fi
        if [ -n "${backup_dir}" ] && [ -d "${backup_dir}" ]; then
          mv "${backup_dir}" node_modules
          INSTALL_STATUS="INSTALL_UNAVAILABLE_DUE_TO_REGISTRY"
          INSTALL_MESSAGE="Registry Netzwerkfehler – vorhandene node_modules unsicher"
          INSTALL_OK=0
          warn "INSTALL" "${REGISTRY_MESSAGE}; Build wird übersprungen" "${hint}"
        else
          INSTALL_STATUS="INSTALL_UNAVAILABLE_DUE_TO_REGISTRY"
          INSTALL_MESSAGE="Registry Netzwerkfehler"
          INSTALL_OK=0
          warn "INSTALL" "${REGISTRY_MESSAGE}" "${hint}"
        fi
      else
        restore_backup_if_needed "${backup_dir}"
        local tail_output
        tail_output="$(tail -n 20 "${install_log}")"
        rm -f "${install_log}"
        fail 13 "INSTALL" "${pm} install fehlgeschlagen" "Siehe Log:\n${tail_output}"
      fi
    else
      rm -rf "${backup_dir}"
      INSTALL_STATUS="OK"
      INSTALL_MESSAGE="Installation erfolgreich"
      INSTALL_OK=1
      info "INSTALL" "${pm} install erfolgreich" "-"
    fi
  fi
  rm -f "${install_log}"

  if [ "${INSTALL_OK}" -eq 1 ] && [ -n "${lock_hint}" ] && [ -f "${lock_hint}" ]; then
    local lock_after
    lock_after="$(capture_file_state "${lock_hint}")"
    if ! states_equal "${lock_state_before}" "${lock_after}"; then
      fail 11 "LOCKFILE" "${lock_hint} wurde verändert" "Setze Lockfile zurück und führe npm ci erneut aus"
    fi
  fi

  if [ "${INSTALL_OK}" -eq 1 ]; then
    check_dev_dependencies || true
  fi

  if [ "${SKIP_TYPECHECK}" = "0" ] && [ "${INSTALL_OK}" -eq 1 ] && [ "${DEV_DEPS_AVAILABLE}" -eq 1 ]; then
    if [ "${#run_cmd[@]}" -gt 0 ] && command -v "${run_cmd[0]}" >/dev/null 2>&1; then
      if has_package_script typecheck 2>/dev/null; then
        info "TYPECHECK" "${pm} run typecheck" "-"
        if ! run_to "${TIMEOUT_SEC}" "${run_cmd[@]}" typecheck >/dev/null 2>&1; then
          fail 13 "TYPECHECK" "typecheck fehlgeschlagen" "Siehe ${pm} run typecheck"
        fi
      fi
    else
      debug "TYPECHECK" "Kein passender Package-Manager für typecheck gefunden" "-"
    fi
  elif [ "${SKIP_TYPECHECK}" = "1" ]; then
    info "TYPECHECK" "Typecheck übersprungen" "-"
  fi

  BUILD_STATUS="PENDING"
  BUILD_MESSAGE="-"

  if [ "${SKIP_BUILD}" = "1" ]; then
    BUILD_STATUS="SKIPPED_BY_FLAG"
    BUILD_MESSAGE="Build übersprungen"
    info "BUILD" "Build übersprungen (SKIP_BUILD=1)" "-"
  elif [ "${INSTALL_OK}" -eq 0 ]; then
    BUILD_STATUS="SKIPPED_DUE_TO_INSTALL"
    BUILD_MESSAGE="Install nicht erfolgreich"
    if [ "${MODE}" = "STRICT" ]; then
      fail 14 "BUILD" "Build unmöglich – Installation fehlgeschlagen" "Behebe Installationsfehler"
    else
      warn "BUILD" "Installation fehlgeschlagen – Build im WARN-Modus übersprungen" "Behebe Registry & führe Skript erneut aus"
    fi
  elif [ "${DEV_DEPS_AVAILABLE}" -eq 0 ]; then
    BUILD_STATUS="SKIPPED_DEV_DEPS"
    BUILD_MESSAGE="DevDependencies fehlen"
    if [ "${MODE}" = "STRICT" ]; then
      fail 14 "BUILD" "DevDependencies fehlen" "Führe npm ci erneut aus"
    else
      warn "BUILD" "DevDependencies fehlen – Build übersprungen" "Führe npm ci nach Registry-Fix erneut aus"
    fi
  else
    if has_package_script build 2>/dev/null; then
      info "BUILD" "${pm} run build" "-"
      if ! run_to "${TIMEOUT_SEC}" "${run_cmd[@]}" build >/dev/null 2>&1; then
        fail 14 "BUILD" "Build fehlgeschlagen" "Siehe ${pm} run build"
      fi
      if [ ! -d dist ] && [ ! -d build ]; then
        fail 14 "BUILD" "Build-Output fehlt (dist/ oder build/)" "Prüfe Build-Skript"
      fi
      BUILD_STATUS="OK"
      BUILD_MESSAGE="Build erfolgreich"
      BUILD_OK=1
    else
      BUILD_STATUS="SKIPPED_NO_SCRIPT"
      BUILD_MESSAGE="Kein Build-Skript definiert"
      info "BUILD" "Kein Build-Skript definiert" "-"
    fi
  fi

  if [ -f public/env.runtime.js ]; then
    debug "env.runtime.js vorhanden" "-"
  else
    if [ -f scripts/gen_env_runtime.mjs ]; then
      if [ "${INSTALL_OK}" -eq 1 ] && [ "${DEV_DEPS_AVAILABLE}" -eq 1 ]; then
        info "RUNTIME_ENV" "Generiere env.runtime.js" "-"
        if ! run_to 60 node scripts/gen_env_runtime.mjs >/dev/null 2>&1; then
          fail 15 "RUNTIME_ENV" "env.runtime.js konnte nicht erzeugt werden" "Führe node scripts/gen_env_runtime.mjs manuell aus"
        fi
        [ -f public/env.runtime.js ] || fail 15 "RUNTIME_ENV" "env.runtime.js fehlt nach Generatorlauf" "Prüfe Generator"
        cleanup_env_runtime=1
      elif [ "${MODE}" = "STRICT" ]; then
        fail 15 "RUNTIME_ENV" "env.runtime.js fehlt – Generator erfordert erfolgreiche Installation" "Behebe Registry/Install und führe Skript erneut aus"
      else
        warn "RUNTIME_ENV" "env.runtime.js fehlt – Generator wird im WARN-Modus übersprungen" "Führe Skript nach Registry-Fix erneut aus"
      fi
    elif [ -f public/env.runtime.js.tpl ]; then
      if [ "${MODE}" = "STRICT" ]; then
        fail 15 "RUNTIME_ENV" "env.runtime.js fehlt (Template gefunden)" "Erzeuge env.runtime.js aus Template"
      else
        warn "RUNTIME_ENV" "env.runtime.js fehlt (Template vorhanden) – WARN-Modus fordert manuelle Generierung" "Erzeuge env.runtime.js nach Registry-Fix"
      fi
    fi
  fi

  info "RESULT" "Installation und Build-Pipeline abgeschlossen" "-"
  FINAL_EXIT=0
  popd >/dev/null
  trap - RETURN
  if [ "${cleanup_env_runtime}" = "1" ]; then
    rm -f "${cleanup_env_runtime_path}"
  fi
  cleanup_env_runtime=0
  exit 0
}

has_package_script(){
  local script_name="$1"
  if command -v jq >/dev/null 2>&1; then
    local script_value
    script_value="$(jq -r --arg name "${script_name}" '.scripts[$name] // empty' package.json 2>/dev/null || true)"
    if [ -n "${script_value}" ]; then
      return 0
    fi
    return 1
  fi

  node - <<'__NODE__' "${script_name}" >/dev/null 2>&1
const fs = require('fs');
const name = process.argv[1];
try {
  const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
  if (pkg.scripts && typeof pkg.scripts[name] === 'string' && pkg.scripts[name].length > 0) {
    process.exit(0);
  }
} catch (err) {}
process.exit(1);
__NODE__
  local status=$?
  if [ "${status}" -eq 0 ]; then
    return 0
  fi
  return 1
}

main "$@"
