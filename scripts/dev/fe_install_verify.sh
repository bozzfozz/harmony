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
: "${REQUIRED_NODE_MAJOR:=20}"
: "${REQUIRED_NPM_MAJOR:=11}"
: "${TIMEOUT_SEC:=600}"
: "${VERBOSE:=0}"
: "${SKIP_INSTALL:=0}"
: "${SKIP_BUILD:=0}"
: "${SKIP_TYPECHECK:=0}"

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

run_to(){
  local secs="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout --preserve-status "${secs}" "$@"
  else
    "$@"
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

  node - <<'EOF' "${script_name}" >/dev/null 2>&1
const fs = require('fs');
const name = process.argv[1];
try {
  const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
  if (pkg.scripts && typeof pkg.scripts[name] === 'string' && pkg.scripts[name].length > 0) {
    process.exit(0);
  }
} catch (err) {}
process.exit(1);
EOF
  local status=$?
  if [ "${status}" -eq 0 ]; then
    return 0
  fi
  return 1
}

main(){
  ensure_boolean "${SKIP_INSTALL}"
  ensure_boolean "${SKIP_BUILD}"
  ensure_boolean "${SKIP_TYPECHECK}"

  [ -d "${FE_DIR}" ] || die 16 "Ordner '${FE_DIR}' fehlt"

  pushd "${FE_DIR}" >/dev/null
  cleanup_env_runtime=0
  cleanup_env_runtime_path="$(pwd)/public/env.runtime.js"
  trap 'if [ "${cleanup_env_runtime}" = "1" ]; then rm -f "${cleanup_env_runtime_path}"; fi' EXIT

  # 1) Toolchain prüfen
  require_cmd node
  require_cmd npm
  local node_major npm_version npm_major
  node_major="$(node --version | sed 's/^v//' | cut -d. -f1)"
  npm_version="$(npm --version 2>/dev/null | tail -n1)"
  npm_major="$(echo "${npm_version}" | cut -d. -f1)"
  if ! [[ "${node_major}" =~ ^[0-9]+$ ]]; then
    die 10 "Node-Version konnte nicht bestimmt werden (erhalten: ${node_major})"
  fi
  if ! [[ "${npm_major}" =~ ^[0-9]+$ ]]; then
    die 10 "npm-Version konnte nicht bestimmt werden (erhalten: ${npm_version})"
  fi
  vlog "Node v${node_major}, npm v${npm_version}"
  [ "${node_major}" -ge "${REQUIRED_NODE_MAJOR}" ] || die 10 "Node-Major zu alt (${node_major}) < ${REQUIRED_NODE_MAJOR}"
  [ "${npm_major}" -ge "${REQUIRED_NPM_MAJOR}" ] || die 10 "NPM-Major zu alt (${npm_major}) < ${REQUIRED_NPM_MAJOR}"

  # 2) Struktur/Manifeste
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

  if [ -f .npmrc ] && ! grep -Eqs '^registry=https://registry\.npmjs\.org/?' .npmrc; then
    die 12 ".npmrc Registry ist nicht npmjs.org"
  fi

  # 3) Installation (deterministisch)
  if [ "${SKIP_INSTALL}" = "0" ]; then
    rm -rf node_modules
    vlog "${pm} install (${lock_hint}) ..."
    run_to "${TIMEOUT_SEC}" "${install_cmd[@]}" || die 13 "${pm} Installation gescheitert"
    [ -d node_modules ] || die 13 "node_modules fehlt nach Installation"
  else
    vlog "Installationsschritt übersprungen"
    [ -d node_modules ] || die 13 "node_modules fehlt (Installation übersprungen)"
  fi

  # 4) Sanity: Kernabhängigkeiten vorhanden (heuristisch, optional)
  node -e "require.resolve('react')" >/dev/null 2>&1 || vlog "Hinweis: 'react' nicht auflösbar (optional)"
  node -e "require.resolve('vite')" >/dev/null 2>&1 || vlog "Hinweis: 'vite' nicht auflösbar (optional)"

  # 5) Optional: Typecheck, wenn definiert
  if [ "${SKIP_TYPECHECK}" = "0" ] && has_package_script typecheck; then
    vlog "${pm} run typecheck ..."
    run_to "${TIMEOUT_SEC}" "${run_cmd[@]}" typecheck || die 13 "typecheck fehlgeschlagen"
  elif [ "${SKIP_TYPECHECK}" = "1" ] && has_package_script typecheck; then
    vlog "Typecheck-Skript vorhanden, aber übersprungen"
  fi

  # 6) Runtime-Config prüfen (env.runtime.js)
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

  # 7) Build
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
