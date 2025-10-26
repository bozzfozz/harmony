#!/bin/sh
set -eu

exec python3 -m app.runtime.container_entrypoint "$@"
