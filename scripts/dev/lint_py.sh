#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

ruff format --check .
ruff check --output-format=concise .
mypy app tests --config-file mypy.ini
