# Changelog

All notable changes to Harmony are documented in this file.

## Unreleased

### Changed
- Switch dependency management to maintained range specifiers in `pyproject.toml`,
  remove the redundant Starlette pin, and convert the requirements files into
  `uv export` pointers so operators can generate locks on demand.

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
