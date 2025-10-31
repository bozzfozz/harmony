# Backup — Security Reference Snapshot

## requirements.txt
```text
# Runtime dependencies for Harmony backend
# FastAPI 0.116.2 and Starlette 0.49.1 passed the full pytest suite, restoring
# the GHSA-2c2j-9gv5-cj73 mitigation while also incorporating the Range header
# DoS fix from GHSA-7f5h-v6xp-fcq8.

fastapi==0.116.2
starlette==0.49.1
uvicorn==0.30.1
sqlalchemy==2.0.31
aiohttp==3.12.14
aiosqlite==0.19.0
spotipy==2.25.1
pydantic==2.7.1
httpx==0.27.0
psutil==5.9.8
mutagen==1.47.0
prometheus-client==0.20.0
Unidecode==1.3.8
```

## requirements-dev.txt
```text
# Developer tooling dependencies
libcst==1.5.1
mypy==1.10.0
pip-audit==2.7.3
radon==6.0.1
ruff==0.6.5
vulture==2.10
```

## requirements-test.txt
```text
# Test-only dependencies
pytest==7.4.4
pytest-asyncio==0.23.6
```

## scripts/dev/pip_audit.sh
```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v pip-audit >/dev/null 2>&1; then
  printf 'pip-audit not found on PATH; attempting automatic installation.\n' >&2

  if [[ -n ${PIP_AUDIT_BOOTSTRAP:-} ]]; then
    read -r -a bootstrap_cmd <<<"${PIP_AUDIT_BOOTSTRAP}"
  else
    if [[ ! -f "requirements-dev.txt" ]]; then
      printf 'requirements-dev.txt is missing; cannot install pip-audit automatically.\n' >&2
      printf 'Install pip-audit manually via "pip install -r requirements-dev.txt".\n' >&2
      exit 1
    fi

    if command -v python3 >/dev/null 2>&1; then
      python_cmd="python3"
    elif command -v python >/dev/null 2>&1; then
      python_cmd="python"
    else
      printf 'Neither python3 nor python is available to install pip-audit.\n' >&2
      exit 1
    fi

    bootstrap_cmd=($python_cmd -m pip install -r requirements-dev.txt)
  fi

  bootstrap_display=$(printf '%q ' "${bootstrap_cmd[@]}")
  if ! "${bootstrap_cmd[@]}"; then
    printf 'Automatic installation of pip-audit failed using command: %s\n' "$bootstrap_display" >&2
    printf 'Install pip-audit manually via "pip install -r requirements-dev.txt" and retry.\n' >&2
    exit 1
  fi

  if ! command -v pip-audit >/dev/null 2>&1; then
    printf 'pip-audit is still unavailable after installation attempt.\n' >&2
    exit 1
  fi

  printf 'pip-audit installed successfully; continuing with vulnerability scans.\n' >&2
fi

if help_output=$(pip-audit --help 2>&1); then
  if grep -q -- '--progress-spinner' <<<"$help_output"; then
    audit_flags=("--progress-spinner" "off")
  elif grep -q -- '--disable-progress-bar' <<<"$help_output"; then
    audit_flags=("--disable-progress-bar")
  else
    audit_flags=()
  fi
else
  printf 'Unable to determine supported pip-audit flags; proceeding without optional arguments.\n' >&2
  audit_flags=()
fi

requirements_files=("requirements.txt")
[[ -f "requirements-dev.txt" ]] && requirements_files+=("requirements-dev.txt")
[[ -f "requirements-test.txt" ]] && requirements_files+=("requirements-test.txt")

for req_file in "${requirements_files[@]}"; do
  printf '==> pip-audit (%s)\n' "$req_file"
  if audit_output=$(pip-audit "${audit_flags[@]}" -r "$req_file" 2>&1); then
    printf '%s\n' "$audit_output"
  else
    printf '%s\n' "$audit_output" >&2
    if grep -qiE 'network|connection|timed out|temporary failure|Name or service not known|offline' <<<"$audit_output"; then
      printf 'pip-audit requires network connectivity to complete. Resolve connectivity issues before rerunning.\n' >&2
    else
      printf 'pip-audit detected vulnerabilities or encountered an error while scanning %s.\n' "$req_file" >&2
    fi
    exit 1
  fi
  printf '\n'
done
```

## Makefile targets
```make
pip-audit:
	./scripts/dev/pip_audit.sh

release-check:
	@python scripts/dev/release_check.py
```

## CHANGELOG.md (Kopfbereich)
```markdown
# Changelog

All notable changes to Harmony are documented in this file.

## Unreleased

- Noch keine Einträge.

## v1.0.1 — Security patch

### Security
- Aktualisiert Starlette auf 0.49.1 zur Behebung der öffentlich bekannten
  DoS-Schwachstelle GHSA-7f5h-v6xp-fcq8 (Range-Header Parsing in FileResponse).
- CI Release-Gate (`make pip-audit`) passiert wieder ohne Findings.

## v1.0.0 — Initial release

### Dependencies
- FastAPI is pinned to 0.116.2 and ships with Starlette 0.48.0, incorporating the
  GHSA-2c2j-9gv5-cj73 security fix.

### Platform
- FastAPI exposes `/live`, `/ready`, `/status` and `/env` so operators can validate deployments, configuration snapshots and external dependencies without touching private routers.【F:app/main.py†L1-L120】【F:app/api/system.py†L1-L260】【F:tests/test_live_endpoint.py†L1-L36】【F:tests/test_system_ready_endpoint.py†L1-L120】【F:tests/test_ready_check.py†L1-L160】【F:tests/test_env_endpoint.py†L1-L80】

### Harmony Download Manager
- The orchestrator schedules watchlist refresh jobs through `WatchlistTimer` and dispatches artist scan/refresh tasks with idempotent queue writes and observability events, powering automated library upkeep.【F:app/orchestrator/timer.py†L1-L220】【F:app/orchestrator/handlers_artist.py†L1-L200】【F:tests/orchestrator/test_watchlist_timer.py†L1-L200】

### Integrations
- Spotify support persists playlist metadata, detects stale snapshots and surfaces backfill job history through dedicated APIs to monitor enrichment progress.【F:app/workers/playlist_sync_worker.py†L1-L260】【F:tests/test_playlist_sync_worker.py†L1-L160】【F:app/api/spotify.py†L1-L260】【F:tests/test_spotify_backfill_history.py†L1-L120】
- Soulseek downloads enrich listings with live queue metadata from `slskd` while tolerating transport failures so operators can triage stalled transfers.【F:app/services/download_service.py†L1-L200】【F:tests/test_download_service.py†L1-L120】

### Operator UX
- The server-rendered `/ui/watchlist` surface lets operators pause, resume and reprioritise artists via HTMX fragments with CSRF protection and consistent error handling.【F:app/ui/routes/watchlist.py†L1-L220】【F:tests/ui/test_watchlist_page.py†L1-L160】
```

## TODO.md (Kopfbereich)
```markdown
# TODO

- ✅ Upgrade Starlette wegen GHSA-7f5h-v6xp-fcq8, um das Range-Header-DoS zu beseitigen und das Release-Gate zu entblocken.
- 🔄 Regelmäßige pip-audit Auswertung in PR-Checks etablieren.
```
