#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' '[dep-sync] Skipping: project is uv-managed (no requirements*.txt).'
exit 0
