# Backup — Security Reference Snapshot

## Dependency manifest

Harmony pins all Python dependencies in [`uv.lock`](uv.lock). Regenerate the lockfile with
`uv lock` after editing `pyproject.toml`, and use `uv export --locked` to emit
`requirements.txt` views for downstream systems that cannot execute uv directly.

## scripts/dev/pip_audit.sh
```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

declare -a pip_audit_cmd
if [[ -n ${PIP_AUDIT_CMD:-} ]]; then
  pip_audit_cmd=($PIP_AUDIT_CMD)
else
  pip_audit_cmd=(uvx pip-audit)
fi

export_requirements() {
  local label=$1
  local output_path=$2
  shift 2

  if ! uv export --locked --format requirements.txt --output-file "$output_path" "$@" >/dev/null 2>&1; then
    return 1
  fi

  if [[ ! -s "$output_path" ]]; then
    rm -f "$output_path"
    return 1
  fi

  printf '%s\n' "$label"
}
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

- _No changes yet._

## v1.0.1 — Dependency compatibility patch

### Fixed
- Align Starlette with FastAPI's `<0.48.0` constraint to resolve pip's resolver conflict while
  keeping a documented waiver for GHSA-7f5h-v6xp-fcq8.

### Security
- Track the scoped GHSA-7f5h-v6xp-fcq8 waiver in `.pip-audit.toml` with an explicit removal gate.

### CI
- Configure `scripts/dev/pip_audit.sh` to load `.pip-audit.toml` when running audits.

### Tests
- Add `tests/test_runtime_import.py` smoke checks to confirm FastAPI/Starlette imports and the
  ASGI application entry point remain available.

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

- [ ] Monitor FastAPI release notes for Starlette >=0.49.1 support.
- [ ] Once FastAPI widens compatibility, bump Starlette to >=0.49.1 and drop the GHSA waiver.
- [ ] Re-run pip-audit without the waiver to confirm a clean security report.
```
