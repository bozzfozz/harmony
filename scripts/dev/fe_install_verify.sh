#!/usr/bin/env bash
set -euo pipefail

# Exit-Codes
# 0 OK
# 10 Toolchain fehlt/inkompatibel
# 11 Lockfile fehlt/inkonsistent
# 12 Registry/Config-Drift
# 13 Installation fehlgeschlagen
# 14 Build fehlgeschlagen
# 15 Runtime-Konfiguration fehlt (env.runtime.js)
# 16 Projektstruktur unvollständig

: "${FE_DIR:=frontend}"
: "${TIMEOUT_SEC:=600}"
: "${VERBOSE:=0}"
: "${SKIP_INSTALL:=0}"
: "${SKIP_BUILD:=0}"
: "${SKIP_TYPECHECK:=0}"
: "${SUPPLY_GUARD_RAN:=0}"

STRICT_ENV="${TOOLCHAIN_STRICT:-true}"
TOOLCHAIN_STRICT_MODE=1
case "$(printf '%s' "${STRICT_ENV}" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off)
    TOOLCHAIN_STRICT_MODE=0
    ;;
  *)
    TOOLCHAIN_STRICT_MODE=1
    ;;
esac

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLCHAIN_NODE_FILE="${REPO_ROOT}/.nvmrc"
TOOLCHAIN_NODE_VERSION_FILE="${REPO_ROOT}/.node-version"
TOOLCHAIN_NPM_FILE="${REPO_ROOT}/${FE_DIR}/.npm-version"
DEFAULT_REGISTRY="https://registry.npmjs.org/"

cleanup_env_runtime=0
cleanup_env_runtime_path=""

log(){ echo "[fe-verify] $*"; }
vlog(){ [ "${VERBOSE}" = "1" ] && echo "[fe-verify] $*"; }

die(){
  local code="$1"
  shift
  echo "[fe-verify] ERROR: $*" >&2
  exit "${code}"
}

toolchain_violation(){
  # $1 component, $2 expected, $3 actual, $4 remediation hint
  local component="$1"
  local expected="$2"
  local actual="$3"
  local hint="$4"
  local message="Toolchain Drift (${component}): erhalten ${actual:-<unbekannt>}, erwartet ${expected}. ${hint}"

  if [ "${TOOLCHAIN_STRICT_MODE}" -eq 1 ]; then
    die 10 "${message}"
  fi

  log "WARN ${message}"
  log "WARN TOOLCHAIN_STRICT=false erkannt – weiterlaufen nur lokal erlaubt."
}

trim(){
  local value="$1"
  printf '%s' "${value}" | tr -d '\r' | sed -e 's/^\s\+//' -e 's/\s\+$//'
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
    die 16 "sha256sum/shasum nicht verfügbar"
  fi
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

ensure_registry_line(){
  local file="$1"
  local context="$2"
  if [ ! -f "${file}" ]; then
    die 12 "${context}: .npmrc fehlt"
  fi
  if ! grep -Eqs '^registry=https://registry\.npmjs\.org/?$' "${file}"; then
    die 12 "${context}: .npmrc Registry != ${DEFAULT_REGISTRY}"
  fi
  if grep -E 'registry=' "${file}" | grep -Ev '^registry=https://registry\.npmjs\.org/?$' >/dev/null 2>&1; then
    die 12 "${context}: zusätzliche Registry-Einträge gefunden"
  fi
}

require_cmd(){
  local c="$1"
  command -v "${c}" >/dev/null 2>&1 || die 10 "Benötigtes Werkzeug fehlt: ${c}"
}

ensure_boolean(){
  local value="$1"
  case "${value}" in
    0|1) ;;
    *) die 16 "Boolesches Flag muss 0 oder 1 sein (erhalten: ${value})" ;;
  esac
}

ensure_module_available(){
  local module="$1"
  local label="${2:-$1}"
  if ! node -e "require.resolve('${module}')" >/dev/null 2>&1; then
    die 13 "Dev dependency '${label}' fehlt – npm install hat vermutlich --omit=dev genutzt (NODE_ENV=production?)"
  fi
  vlog "${label} auflösbar"
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

maybe_run_supply_guard(){
  if [ "${SUPPLY_GUARD_RAN}" = "1" ]; then
    return
  fi
  local guard_script="${REPO_ROOT}/scripts/dev/supply_guard.sh"
  if [ -x "${guard_script}" ]; then
    vlog "Starte supply-guard ..."
    SUPPLY_GUARD_RAN=1 bash "${guard_script}"
    SUPPLY_GUARD_RAN=1
  else
    vlog "supply-guard Skript nicht gefunden"
  fi
}

main(){
  ensure_boolean "${SKIP_INSTALL}"
  ensure_boolean "${SKIP_BUILD}"
  ensure_boolean "${SKIP_TYPECHECK}"
  ensure_boolean "${SUPPLY_GUARD_RAN}"

  if [ "${SKIP_INSTALL}" = "1" ]; then
    die 16 "SKIP_INSTALL=1 wird nicht unterstützt"
  fi

  [ -d "${REPO_ROOT}/${FE_DIR}" ] || die 16 "Ordner '${FE_DIR}' fehlt"

  cd "${REPO_ROOT}" >/dev/null

  require_cmd node
  require_cmd npm

  if [ ! -f "${TOOLCHAIN_NODE_FILE}" ]; then
    die 16 "Toolchain-Datei ${TOOLCHAIN_NODE_FILE} fehlt"
  fi
  if [ ! -f "${TOOLCHAIN_NODE_VERSION_FILE}" ]; then
    die 16 "Toolchain-Datei ${TOOLCHAIN_NODE_VERSION_FILE} fehlt"
  fi
  if [ ! -f "${TOOLCHAIN_NPM_FILE}" ]; then
    die 16 "Toolchain-Datei ${TOOLCHAIN_NPM_FILE} fehlt"
  fi

  local required_node required_npm alt_node node_version npm_version
  required_node=$(trim "$(cat "${TOOLCHAIN_NODE_FILE}")")
  alt_node=$(trim "$(cat "${TOOLCHAIN_NODE_VERSION_FILE}")")
  required_npm=$(trim "$(cat "${TOOLCHAIN_NPM_FILE}")")

  if [ -z "${required_node}" ]; then
    die 16 "Toolchain-Datei ${TOOLCHAIN_NODE_FILE} ist leer"
  fi
  if [ -z "${alt_node}" ]; then
    die 16 "Toolchain-Datei ${TOOLCHAIN_NODE_VERSION_FILE} ist leer"
  fi
  if [ "${required_node}" != "${alt_node}" ]; then
    die 16 ".node-version (${alt_node}) weicht von .nvmrc (${required_node}) ab"
  fi
  if [ -z "${required_npm}" ]; then
    die 16 "Toolchain-Datei ${TOOLCHAIN_NPM_FILE} ist leer"
  fi

  node_version="$(node --version | sed 's/^v//')"
  npm_version="$(npm --version 2>/dev/null | tail -n1)"
  if [ "${node_version}" != "${required_node}" ]; then
    toolchain_violation "Node.js" "${required_node}" "${node_version}" "Fix: nvm install ${required_node} && nvm use ${required_node}"
  fi
  if [ "${npm_version}" != "${required_npm}" ]; then
    toolchain_violation "npm" "${required_npm}" "${npm_version}" "Fix: npm install -g npm@${required_npm}"
  fi
  vlog "Node ${node_version}, npm ${npm_version}"

  ensure_registry_line "${REPO_ROOT}/.npmrc" "repo-root"
  ensure_registry_line "${REPO_ROOT}/${FE_DIR}/.npmrc" "${FE_DIR}"

  local npm_config_registry
  npm_config_registry="$(normalize_registry "$(npm config get registry 2>/dev/null || true)")"
  if [ "${npm_config_registry}" != "${DEFAULT_REGISTRY}" ]; then
    die 12 "npm config registry ist '${npm_config_registry}', erwartet ${DEFAULT_REGISTRY}"
  fi

  maybe_run_supply_guard

  pushd "${REPO_ROOT}/${FE_DIR}" >/dev/null
  cleanup_env_runtime=0
  cleanup_env_runtime_path="$(pwd)/public/env.runtime.js"
  trap 'if [ "${cleanup_env_runtime}" = "1" ]; then rm -f "${cleanup_env_runtime_path}"; fi' EXIT

  [ -f package.json ] || die 16 "package.json fehlt"

  local pm="" lock_hint=""
  declare -a install_cmd=()
  declare -a run_cmd=()
  if [ -f package-lock.json ]; then
    pm="npm"
    lock_hint="package-lock.json"
    install_cmd=(npm ci --no-audit --no-fund)
    run_cmd=(npm run)
  elif [ -f pnpm-lock.yaml ]; then
    pm="pnpm"
    lock_hint="pnpm-lock.yaml"
    require_cmd pnpm
    install_cmd=(pnpm install --frozen-lockfile)
    run_cmd=(pnpm run)
  elif [ -f yarn.lock ]; then
    pm="yarn"
    lock_hint="yarn.lock"
    require_cmd yarn
    install_cmd=(yarn install --frozen-lockfile)
    run_cmd=(yarn run)
  else
    die 11 "Lockfile fehlt (package-lock.json|pnpm-lock.yaml|yarn.lock)"
  fi

  local lock_hash_before=""
  if [ -n "${lock_hint}" ] && [ -f "${lock_hint}" ]; then
    lock_hash_before="$(sha256_file "${lock_hint}")"
  fi

  vlog "npm cache verify ..."
  run_to "${TIMEOUT_SEC}" npm cache verify >/dev/null 2>&1 || die 13 "npm cache verify fehlgeschlagen"
  vlog "npm cache clean --force ..."
  run_to "${TIMEOUT_SEC}" npm cache clean --force >/dev/null 2>&1 || die 13 "npm cache clean fehlgeschlagen"

  if [ "${SKIP_INSTALL}" = "0" ]; then
    rm -rf node_modules
    vlog "${pm} install (${lock_hint}) ..."
    run_to "${TIMEOUT_SEC}" "${install_cmd[@]}" || die 13 "${pm} Installation gescheitert"
    [ -d node_modules ] || die 13 "node_modules fehlt nach Installation"
  else
    vlog "Installationsschritt übersprungen"
    [ -d node_modules ] || die 13 "node_modules fehlt (Installation übersprungen)"
  fi

  if [ -n "${lock_hint}" ] && [ -f "${lock_hint}" ]; then
    local lock_hash_after
    lock_hash_after="$(sha256_file "${lock_hint}")"
    if [ "${lock_hash_after}" != "${lock_hash_before}" ]; then
      die 11 "${lock_hint} wurde verändert. Lockfile mit gepinnter Toolchain neu erzeugen."
    fi
  fi

  ensure_module_available "vite" "vite"
  ensure_module_available "typescript" "typescript"

  if [ "${SKIP_TYPECHECK}" = "0" ] && has_package_script typecheck; then
    vlog "${pm} run typecheck ..."
    run_to "${TIMEOUT_SEC}" "${run_cmd[@]}" typecheck || die 13 "typecheck fehlgeschlagen"
  elif [ "${SKIP_TYPECHECK}" = "1" ] && has_package_script typecheck; then
    vlog "Typecheck-Skript vorhanden, aber übersprungen"
  fi

  if [ -f public/env.runtime.js ]; then
    vlog "env.runtime.js vorhanden"
  else
    if [ -f scripts/gen_env_runtime.mjs ]; then
      vlog "generiere env.runtime.js ..."
      run_to 60 node scripts/gen_env_runtime.mjs || die 15 "env.runtime.js konnte nicht erzeugt werden"
      [ -f public/env.runtime.js ] || die 15 "env.runtime.js fehlt nach Generatorlauf"
      cleanup_env_runtime=1
    elif [ -f public/env.runtime.js.tpl ]; then
      die 15 "env.runtime.js fehlt (Template gefunden). Generator/Copy-Step erforderlich."
    else
      vlog "Kein env.runtime.js benötigt (kein Template/Generator gefunden)"
    fi
  fi

  if [ "${SKIP_BUILD}" = "0" ]; then
    if has_package_script build; then
      vlog "${pm} run build ..."
      run_to "${TIMEOUT_SEC}" "${run_cmd[@]}" build || die 14 "Build fehlgeschlagen"
      if [ ! -d dist ] && [ ! -d build ]; then
        die 14 "Build-Output fehlt (dist/ oder build/)"
      fi
    else
      vlog "Kein Build-Skript definiert"
    fi
  else
    if has_package_script build; then
      vlog "Build-Skript vorhanden, aber übersprungen"
    else
      vlog "Build-Schritt übersprungen (kein Skript definiert)"
    fi
  fi

  popd >/dev/null
  if [ "${cleanup_env_runtime}" = "1" ]; then
    rm -f "${cleanup_env_runtime_path}"
  fi
  trap - EXIT
  log "OK: Installation und Build erfolgreich"
}

main "$@"
