#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if [[ -z "${CI:-}" ]]; then
  ./scripts/dev/auto_repair.py fmt
fi

./scripts/dev/auto_repair.py lint
./scripts/dev/auto_repair.py types
