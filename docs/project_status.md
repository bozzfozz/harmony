# Projektstatus Harmony Backend

## Gesamtüberblick
- Die fehlende `activity_events`-Migration ist ausgerollt; Admin-Flows und Postgres-Migrationstests laufen wieder ohne `UndefinedTable`. 【F:app/migrations/versions/202411181200_create_activity_events_table.py†L1-L35】【F:tests/migrations/test_upgrade_downgrade_postgres.py†L1-L44】
- Observability-Signale wurden repariert: Scheduler-Leases schreiben erneut auf `app.orchestrator.metrics`, die Search-API emittiert `api.request`-Events und die Dokumentation beschreibt die Logger-Verträge. 【F:app/orchestrator/scheduler.py†L1-L180】【F:app/api/search.py†L1-L140】【F:docs/observability.md†L34-L56】
- Runtime-Diagnosen respektieren Overrides (`/system/stats`), Playlist-Sync invalidiert Caches inkl. Detailpfade und Admin-Fixtures stellen den globalen FastAPI-Zustand nach jedem Test wieder her. 【F:app/api/system.py†L1-L460】【F:app/workers/playlist_sync_worker.py†L1-L140】【F:tests/api/test_admin_artists.py†L1-L220】
- Bandit-Integration ist weiterhin als P2 offen und wird separat abgeschlossen. 【F:ToDo.md†L131-L156】

## Fertiggestellte Arbeiten
- **TD-20251008-001 – `activity_events`-Migration wiederhergestellt:** Alembic-Skript erstellt Tabelle inklusive Index; Migrations-Smoke-Tests prüfen JSONB/TIMESTAMPTZ-Schema. 【F:app/migrations/versions/202411181200_create_activity_events_table.py†L1-L35】【F:tests/migrations/test_upgrade_downgrade_postgres.py†L1-L44】
- **TD-20251008-002 – Orchestrator-Lease-Telemetrie:** Scheduler verwendet wieder den Metrics-Logger; Regressionstest prüft `orchestrator.lease`-Events. 【F:app/orchestrator/scheduler.py†L1-L180】【F:tests/orchestrator/test_scheduler.py†L1-L120】
- **TD-20251008-003 – Search-API-Request-Telemetrie:** `_emit_api_event` ruft deterministisch `app.logging_events.log_event` und deckt Legacy-Shims ab. 【F:app/api/search.py†L1-L140】【F:tests/routers/test_search_logging.py†L1-L120】
- **TD-20251008-004 – psutil-Overrides:** Resolver priorisiert Dependency-Overrides, `app.state.psutil` und Kompatibilitäts-Shims. 【F:app/api/system.py†L360-L460】【F:tests/test_system.py†L1-L120】
- **TD-20251008-005 – Spotify-Status entkoppelt vom Cache:** Cache-Regeln angepasst, sodass Credential-Änderungen sofort sichtbar sind; Regressionstest deckt den Flow ab. 【F:ToDo.md†L70-L96】
- **TD-20251008-006 – Playlist-Cache-Invalidierung:** Invalidator leert List- und Detail-Caches inklusive Pfad-Präfixen und protokolliert betroffene IDs. 【F:app/workers/playlist_sync_worker.py†L1-L140】【F:tests/spotify/test_playlist_cache_invalidation.py†L1-L40】
- **TD-20251008-007 – Admin-Fixture stabilisiert:** Tests deregistrieren Admin-Routen und setzen das OpenAPI-Schema zurück, wodurch Snapshot-Drift vermieden wird. 【F:tests/api/test_admin_artists.py†L1-L220】【F:tests/snapshots/test_openapi_schema.py†L1-L40】
- **TD-20251008-008 – isort-Erzwingung:** Import-Formatierung bereinigt und CI-Gate ergänzt; Dokumentation aktualisiert. 【F:ToDo.md†L108-L129】

## Laufende Arbeiten
- **TD-20251008-009 – Bandit-Sicherheits-Scanning:** Abhängigkeit und CI-Integration stehen, erste Findings müssen noch aufgearbeitet und dokumentiert werden. 【F:ToDo.md†L131-L156】

## Offene Aufgaben (Priorität ≥ P1)
- Keine offenen P0/P1-Issues; Fokus liegt auf dem Abschluss der Bandit-Sicherheitsarbeiten (P2). 【F:ToDo.md†L131-L156】

## Empfohlene nächsten Schritte
1. Bandit-Erstlauf analysieren, Findings triagieren und Dokumentation für Security-Gates vervollständigen.
2. Security-Gate in CI finalisieren und Rollout kommunizieren.
