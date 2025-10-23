# Projektstatus Harmony Backend

## Gesamtüberblick
- Harmony v1.0.0 bündelt das öffentliche FastAPI-API, Health-Surfaces und die Umgebungsprojektion `/env`, damit Deployments SQLite, Soulseek (slskd) und Worker-Zustände ohne interne Router prüfen können.【F:app/main.py†L1-L160】【F:app/api/system.py†L1-L260】【F:tests/test_live_endpoint.py†L1-L36】【F:tests/test_system_ready_endpoint.py†L1-L120】【F:tests/test_ready_check.py†L1-L160】【F:tests/test_env_endpoint.py†L1-L80】
- Der Harmony Download Manager (HDM) taktet Watchlist-Refreshes und Künstler-Scans über den `WatchlistTimer` und sorgt mit idempotenten Queue-Schreibungen für nachvollziehbare Automatisierung.【F:app/orchestrator/timer.py†L1-L220】【F:app/orchestrator/handlers_artist.py†L1-L200】【F:tests/orchestrator/test_watchlist_timer.py†L1-L200】
- Die serverseitige `/ui/watchlist`-Oberfläche erlaubt Pause, Resume und Prioritätsanpassungen mit CSRF-Schutz und fragmentbasierter Aktualisierung.【F:app/ui/routes/watchlist.py†L1-L220】【F:tests/ui/test_watchlist_page.py†L1-L160】

## Qualitätsbaseline
- GitHub Actions führt im Workflow [`backend-ci`](../.github/workflows/ci.yml) Formatierung, Linting, Typprüfungen, Pytests und Smoke-Checks sequenziell aus (`make fmt`, `make lint`, `make test`, `make smoke`).
- Die Makefile-Targets [`fmt`, `lint`, `types`, `test`](../Makefile) nutzen die Auto-Repair-Engine, um `ruff`, `mypy` und `pytest` deterministisch zu fahren und bei Bedarf Auto-Fixes zu versuchen.【F:scripts/auto_repair/engine.py†L452-L504】
- Das neue Target [`make docs-verify`](../Makefile) ruft [`scripts/docs_reference_guard.py`](../scripts/docs_reference_guard.py) auf und bricht, sobald Dokumentation auf nicht existente Pfade verweist. Der Guard deckt neben `README.md`, `CHANGELOG.md` und `docs/project_status.md` jetzt auch zentrale Operator-Guides wie `docs/README.md`, `docs/overview.md`, `docs/architecture.md`, `docs/observability.md`, `docs/security.md`, `docs/testing.md`, `docs/troubleshooting.md` sowie sämtliche Playbooks unter `docs/operations/` (inkl. `runbooks/hdm.md`) ab.

## Verifizierte Artefakte
- Ready-/Status-Checks aggregieren Datei-basiertes SQLite, Soulseek-Erreichbarkeit und Idempotency-Konfiguration mit aussagekräftigen Fehlern.【F:app/ops/selfcheck.py†L1-L220】【F:tests/test_ready_check.py†L1-L160】
- Soulseek-Downloads werden mit Live-Queue-Metadaten angereichert; Transportfehler degraden zu beobachtbaren Nullwerten statt Hard-Failures.【F:app/services/download_service.py†L1-L200】【F:tests/test_download_service.py†L1-L120】
- Spotify-Playlist-Sync markiert Snapshots als stale, respektiert konfigurierbare Zeitfenster und das Backfill-API liefert aufbereitete Job-Historie.【F:app/workers/playlist_sync_worker.py†L1-L260】【F:tests/test_playlist_sync_worker.py†L1-L160】【F:app/api/spotify.py†L1-L260】【F:tests/test_spotify_backfill_history.py†L1-L120】

## Empfohlene nächsten Schritte
1. Den Referenz-Guard auf weitere Kern-Dokumente (z. B. `docs/overview.md`, `README.md`) ausweiten, sobald deren Pfadkonventionen stabil sind.
2. UI-Fragmente für weitere HDM-Flows (Downloads, DLQ) mit dedizierten Tests hinterlegen, um die SSR-Oberfläche konsistent abzudecken.
