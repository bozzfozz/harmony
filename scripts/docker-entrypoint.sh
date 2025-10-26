#!/usr/bin/env sh
set -euo pipefail

exec python3 -m app.runtime.container_entrypoint "$@"
