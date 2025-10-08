#!/command/with-contenv bash
set -euo pipefail

TEMPLATE_PATH="/config/www/env.runtime.js.tpl"
OUTPUT_PATH="/config/www/env.runtime.js"

log() {
  echo "[frontend-runtime] $*"
}

prepare_runtime_env() {
  if [[ ! -f "${TEMPLATE_PATH}" ]]; then
    log "template ${TEMPLATE_PATH} not found; skipping runtime env rendering"
    return
  fi

  export PUBLIC_BACKEND_URL="${PUBLIC_BACKEND_URL:-}"
  export PUBLIC_SENTRY_DSN="${PUBLIC_SENTRY_DSN:-}"
  if [[ -n "${PUBLIC_FEATURE_FLAGS:-}" ]]; then
    export PUBLIC_FEATURE_FLAGS="${PUBLIC_FEATURE_FLAGS}"
  else
    export PUBLIC_FEATURE_FLAGS='{}'
  fi

  tmp_file="$(mktemp)"
  envsubst '${PUBLIC_BACKEND_URL} ${PUBLIC_SENTRY_DSN} ${PUBLIC_FEATURE_FLAGS}' <"${TEMPLATE_PATH}" >"${tmp_file}"
  mv "${tmp_file}" "${OUTPUT_PATH}"
  chmod 644 "${OUTPUT_PATH}"
  chown abc:abc "${OUTPUT_PATH}" 2>/dev/null || true
  log "rendered runtime env to ${OUTPUT_PATH}"
}

prepare_runtime_env
