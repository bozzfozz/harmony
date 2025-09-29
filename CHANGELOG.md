## v1.0.1 — 2025-09-25
- docs: AGENTS.md um Initiative-, Scope-Guard- und Clarification-Regeln inkl. Checklisten, CI-Gates und Beispielen erweitert.
- docs: README/ENV aktualisiert, Health/Ready/Metrics-Doku konsolidiert,
  `.env.example` ergänzt und neue Ops-Guides für Runtime-Konfiguration sowie
  Prometheus-Integration hinzugefügt.【F:README.md†L328-L612】【F:.env.example†L1-L108】【F:docs/ops/runtime-config.md†L1-L83】【F:docs/ops/metrics.md†L1-L61】
- feat(watchlist): persistenter Cooldown speichert `retry_block_until`, Worker überspringt gesperrte Artists und löscht den Wert nach Erfolg; Migration, Tests und Doku decken Verhalten und Logs ab.【F:app/models.py†L205-L212】【F:app/services/watchlist_dao.py†L17-L153】【F:app/workers/watchlist_worker.py†L102-L428】【F:app/migrations/versions/b4e3a1f6c8f6_add_retry_block_until_watchlist.py†L1-L46】【F:tests/workers/test_watchlist_cooldown.py†L1-L123】【F:docs/worker_watchlist.md†L15-L63】
- chore(conf): konservative Watchlist-Defaults mit Retry-Budget und Cooldown
  festgeschrieben, Worker-Backoff gedeckelt, neue Tests und README-Tabelle
  dokumentieren die Limits.【F:app/config.py†L114-L200】【F:app/workers/watchlist_worker.py†L1-L420】【F:tests/workers/test_watchlist_defaults.py†L1-L260】【F:README.md†L87-L104】
- perf(worker): entblockt den Watchlist-Worker mit konfigurierbarem DB-I/O,
  strikten Spotify-/Soulseek-Timeouts, begrenzter Parallelität und
  exponentiellem Retry-Backoff; aktualisierte Tests und Dokumentation
  begleiten den Rollout.【F:app/workers/watchlist_worker.py†L1-L382】【F:app/services/watchlist_dao.py†L1-L201】【F:app/config.py†L114-L189】【F:docs/worker_watchlist.md†L1-L85】【F:tests/workers/test_watchlist_worker.py†L1-L229】
- feat(integrations): async Soulseek adapter with retry/backoff, normalized
  TrackCandidate mapping and integration service delegation. 【F:app/integrations/slskd_adapter.py†L1-L302】【F:app/services/integration_service.py†L1-L123】【F:tests/integrations/test_slskd_adapter.py†L1-L196】【F:tests/services/test_integration_service_slskd.py†L1-L135】
- feat(frontend): Downloads-Tab ergänzt eine Fehlgeschlagen-Badge samt Inline-Steuerung (Retry, Entfernen, Retry-All mit Bestätigungsdialog) und deaktiviert Polling in inaktiven Tabs.
- docs: `AGENTS.md` – Initiative Policy, Scope-Guard, Clarification & PR-Regeln ergänzt.
- Refine AGENTS.md: Commit-Hygiene, Branch-Regel ein Ziel, Testing-Erwartungen, Quality-Gates (ruff/black, eslint/prettier, bandit/npm audit), AI-Review-Pflicht, Lizenz-Header, TASK_ID- und Testnachweise-Pflicht.
- Update PR-Template: TASK_ID und Testnachweise verpflichtend.
- chore(core): Transfers-Wrapper typisiert, Fehler auf `VALIDATION_ERROR`/`NOT_FOUND`/`DEPENDENCY_ERROR` gemappt und Import-Sanity-Tests ergänzt.【F:app/core/transfers_api.py†L1-L188】【F:app/core/soulseek_client.py†L1-L190】【F:tests/core/test_transfers_api.py†L1-L124】【F:tests/core/test_imports.py†L1-L27】

# Changelog
- feat(cache): introduce HTTP conditional requests with strong/weak ETag support, Last-Modified propagation, documented 304
  responses and an in-memory TTL+LRU response cache with automatic invalidation hooks and configuration via `CACHE_*` variables.

## v1.x.x
- feat(match): Unicode/alias-normalisierte Matching-Pipeline inkl. Editions-Bonus, Confidence-Score und Album-Completion-Bewertung.【F:app/core/matching_engine.py†L1-L238】【F:app/services/library_service.py†L1-L156】【F:app/utils/text_normalization.py†L1-L215】【F:tests/test_matching_engine.py†L1-L93】【F:tests/test_text_normalization.py†L1-L38】
- test(lifespan): add dedicated FastAPI lifespan and worker lifecycle coverage with
  stubbed workers, including startup failures, idempotent shutdown and
  cancellation scenarios.【F:tests/test_lifespan_workers.py†L1-L165】【F:tests/fixtures/worker_stubs.py†L1-L154】
- refactor(worker): make the watchlist worker async-safe with DAO backed
  database access, configurable timeouts/backoff and deterministic shutdown; see
  `docs/worker_watchlist.md` for the updated architecture.【F:app/workers/watchlist_worker.py†L1-L341】【F:app/services/watchlist_dao.py†L1-L189】【F:docs/worker_watchlist.md†L1-L74】

- feat(int): add async slskd track search adapter with deterministic timeout, error mapping and
  documented integration contract.【F:app/integrations/slskd_adapter.py†L1-L211】【F:app/services/integration_service.py†L1-L73】【F:docs/integrations/slskd.md†L1-L84】
- feat(api): vereinheitlichte Fehlerbehandlung mit globalem FastAPI-Handler, Fehlerklassen und einem stabilen Fehler-Envelope (`ok=false`, `error{code,message,meta}`); OpenAPI veröffentlicht `ErrorResponse`, Tests decken Mapping (Validation, Not Found, Rate Limit, Dependency, Internal) sowie Debug-Header ab.【F:app/errors.py†L1-L231】【F:app/main.py†L1-L458】【F:tests/test_errors_contract.py†L1-L104】
- feat(conf): Secret-Validierung für slskd/Spotify mit Live-Ping, Timeout-Fallback (`mode: format`), API-Endpoint `/api/v1/secrets/{provider}/validate`, UI-Panel „Jetzt testen“ sowie Dokumentation und Tests.【F:app/services/secret_validation.py†L1-L248】【F:app/routers/system_router.py†L1-L260】【F:frontend/src/pages/Settings/SecretsPanel.tsx†L1-L143】【F:tests/test_secret_validation.py†L1-L271】【F:docs/secrets.md†L1-L104】
- feat(obs): introduce `/api/v1/health`, `/api/v1/ready` and a Prometheus `/metrics` exporter with configurable auth/timeouts plus documentation and tests.【F:app/services/health.py†L1-L152】【F:app/routers/system_router.py†L1-L210】【F:app/main.py†L1-L910】【F:tests/test_health_ready.py†L1-L223】【F:docs/observability.md†L1-L86】
- feat(dlq): expose `/api/v1/dlq` management endpoints (list, bulk requeue, purge, stats), update metrics registry with custom gauges/counters and document operational workflows.【F:app/services/dlq_service.py†L1-L355】【F:app/routers/dlq_router.py†L1-L228】【F:app/main.py†L1-L915】【F:docs/operations/dlq.md†L1-L144】【F:tests/test_dlq_router.py†L1-L146】【F:tests/test_dlq_service.py†L1-L152】
- fix(frontend): lazy load Library tabs, gate queries/toasts to the active view and sync the tab state with the URL to eliminate background polling.
- feat(frontend): introduce a unified Library page with shadcn/ui tabs for artists, downloads and watchlist while redirecting legacy routes to the new entry point.
- sec: enforce global API-Key authentication for all routers, return RFC 7807 problem-details for 401/403, document the scheme in OpenAPI, add configurable allowlist and restrictive CORS via env (`HARMONY_API_KEYS`, `AUTH_ALLOWLIST`, `ALLOWED_ORIGINS`).
- feat: versioniere alle produktiven Endpunkte unter `/api/v1`, dokumentiere die neue Basis in OpenAPI/Docs, führe das Flag `FEATURE_ENABLE_LEGACY_ROUTES` zur temporären Alias-Bereitstellung ein und aktualisiere das Frontend auf den versionierten Pfad (`API_BASE_PATH`, `VITE_API_BASE_PATH`).
- feat: add feature flags for artwork and lyrics (default disabled) with conditional worker wiring, 503 guards, and refreshed documentation/tests.
- refactor: purge remaining Plex/Beets wiring, ensure routers/workers only load Spotify & Soulseek, add wiring audit guard, and refresh docs/tests.
- infra: replace ad-hoc schema management with Alembic migrations (`init_db` runs `alembic upgrade head`, Docker entrypoint applies migrations automatically, Makefile gains `db.upgrade`/`db.revision`, README documents the flow, and the initial revision seeds missing columns/indexes).【F:app/db.py†L1-L107】【F:scripts/docker-entrypoint.sh†L1-L11】【F:Makefile†L1-L48】【F:README.md†L189-L202】【F:alembic.ini†L1-L29】【F:app/migrations/versions/7c9bdb5e1a3d_create_base_schema.py†L1-L111】
- fix: offload Spotify lookups in the watchlist worker to executor threads to
  prevent event-loop starvation and add regression coverage around the
  cancellation-safe path.
- chore: code hygiene sweep – migrate FastAPI startup/shutdown handling to the
  lifespan API, refresh deprecated status-code constants, and document the
  current code-health baseline.
- ci: add dev toolchain (bandit/radon/vulture/pip-audit) with offline fallback
  targets and extended CI gates across security and analysis tooling.
- fix: preserve FREE ingest partial failure details when skips occur and surface
  skip metadata (queued/failed/skipped counts, skip reason) in job status
  responses.
- Unified ingest pipeline for Spotify FREE and PRO sources: shared job/item states
  (`registered` → `normalized` → `queued` → `completed`/`failed`), consistent metrics
  (`ingest_normalized`, `ingest_enqueued`, `ingest_skipped`, `ingest_completed`),
  optional backpressure via `INGEST_MAX_PENDING_JOBS`, configurable chunking with
  `INGEST_BATCH_SIZE`, partial success responses (HTTP 207 + structured `error`)
  instead of hard failures, and enriched job status snapshots including accepted
  vs. skipped counts.
- Spotify FREE Ingest – neue Endpunkte (`POST /spotify/import/free`, `POST /spotify/import/free/upload`, `GET /spotify/import/jobs/{id}`) erfassen bis zu 100 Spotify-Playlist-Links sowie große Tracklisten ohne OAuth, normalisieren die Einträge (Artist/Titel/Album/Dauer), deduplizieren sie, erzeugen persistente `ingest_jobs`/`ingest_items` Datensätze und übergeben normalisierte Batches direkt an den bestehenden Soulseek-Sync-Worker. File-Uploads (CSV/TXT/JSON) werden serverseitig gestreamt geparst, Limits (`FREE_MAX_PLAYLISTS`, `FREE_MAX_TRACKS_PER_REQUEST`, `FREE_BATCH_SIZE`) sind konfigurierbar, Job-Status liefert registrierte/queued/failed Counts und Skip-Gründe.
- Spotify PRO Backfill – neue Tabelle `backfill_jobs`, Spotify-Cache (`spotify_cache`) und Worker, der FREE-Ingest-Items ohne `spotify_track_id` mit Spotify-Suche/Heuristiken (`artist`/`title`/`album`/Dauer±2s) abgleicht, ISRC/Dauer aktualisiert, Cache-Hits protokolliert und Playlist-Links bei Bedarf über die API expandiert (`POST /spotify/backfill/run`, `GET /spotify/backfill/jobs/{id}`). Konfigurierbar per `BACKFILL_MAX_ITEMS` und `BACKFILL_CACHE_TTL_SEC`.
- Smart Search v2 – `/search` bündelt Spotify-, Plex- und Soulseek-Ergebnisse in einem normalisierten Schema inklusive Score, Bitrate/Format, erweiterten Filtern (Typ, Genre, Jahr, Dauer, Explicit, Mindestbitrate, bevorzugte Formate, Soulseek-Username), Sortierung (`relevance`, `bitrate`, `year`, `duration`) und Pagination.
- Spotify FREE-Modus – neuer Modus-Schalter (`GET/POST /spotify/mode`) plus Parser- und Enqueue-Endpunkte (`/spotify/free/*`) für text- oder dateibasierte Imports ohne OAuth inkl. FLAC-Priorisierung im SyncWorker.
- Spotify FREE Playlist-Ingest – `/imports/free` akzeptiert bis zu 1 000 Playlist-Links pro Anfrage (JSON, CSV, TXT), validiert ausschließlich echte Playlists, legt `import_sessions`/`import_batches`-Stubjobs an und meldet akzeptierte, übersprungene und abgelehnte Links inkl. Limits (`max_links`, `max_body_bytes`).
- Smart Search Advanced – `/api/search` unterstützt strukturierte Filter (Typ, Genre, Jahrbereich, Mindestbitrate, Format-Prioritäten), konsistente Normalisierung inkl. Score-Boosts sowie eine aktualisierte API-Dokumentation mit Fehlercodes (`DEPENDENCY_ERROR`, `INTERNAL_ERROR`).
- Integrationen vereinheitlicht – neues `MusicProvider`-Interface für Spotify/Plex/slskd, ProviderRegistry mit `INTEGRATIONS_ENABLED`-Flag, Diagnose-Endpoint `GET /api/v1/integrations` und Tests für das Adapter-Contract. Fehler werden auf `DEPENDENCY_ERROR` abgebildet.
- Plex Lean Mode – `/plex` reduziert auf Status, Bibliotheken, deduplizierte Scan-Trigger sowie schlanke Such- und Track-Endpunkte; Playlists/Sessions/Livetv wurden entfernt.
- High-Quality Artwork – Downloads enthalten automatisch eingebettete Cover in Originalauflösung. Der Worker prüft bestehende Embeds und ersetzt nur fehlende oder als „low-res“ erkannte Cover (`ARTWORK_MIN_EDGE`, `ARTWORK_MIN_BYTES`). Artwork-Dateien werden pro `spotify_album_id` bzw. MusicBrainz-Release-Group (`<id>_original.<ext>`) zwischengespeichert (konfigurierbar via `ARTWORK_DIR`, `ARTWORK_HTTP_TIMEOUT`, `ARTWORK_MAX_BYTES`, `ARTWORK_WORKER_CONCURRENCY`). Optionaler Fallback auf MusicBrainz + Cover Art Archive (`ARTWORK_FALLBACK_ENABLED`, `ARTWORK_FALLBACK_PROVIDER`, `ARTWORK_FALLBACK_TIMEOUT_SEC`, `ARTWORK_FALLBACK_MAX_BYTES`) respektiert eine strikte Host-Allowlist. Bei aktivem `BEETS_POSTSTEP_ENABLED` triggert Harmony nach erfolgreichem Einbetten automatisch `beet write`/`beet update`. Neue API-Endpunkte: `GET /soulseek/download/{id}/artwork` (liefert Bild oder `404`) und `POST /soulseek/download/{id}/artwork/refresh` (erneut einreihen). Download-Datensätze speichern die zugehörigen Spotify-IDs (`spotify_track_id`, `spotify_album_id`).
- File Organization – abgeschlossene Downloads werden automatisch nach `Artist/Album/Track` in den Musik-Ordner (`MUSIC_DIR`, Default `./music`) verschoben. Auch Alben ohne Metadaten landen in einem eigenen `<Unknown Album>`-Verzeichnis, Dateinamen werden normalisiert und Duplikate mit Suffixen (`_1`, `_2`, …) abgelegt. Der endgültige Pfad steht in der Datenbank (`downloads.organized_path`) sowie in `GET /soulseek/downloads` zur Verfügung.
- Rich Metadata – alle Downloads enthalten zusätzliche Tags (Genre, Komponist, Produzent, ISRC, Copyright), werden direkt in die Dateien geschrieben und lassen sich per `GET /soulseek/download/{id}/metadata` abrufen oder über `POST /soulseek/download/{id}/metadata/refresh` neu befüllen.
- Complete Discographies – gesamte Künstlerdiskografien können automatisch heruntergeladen und kategorisiert werden.
- Automatic Lyrics – Downloads enthalten jetzt synchronisierte `.lrc`-Dateien mit Songtexten aus der Spotify-API (Fallback Musixmatch/lyrics.ovh) samt neuen Endpunkten zum Abruf und Refresh.
- Artist Watchlist – neue Tabelle `watchlist_artists`, API-Endpunkte (`GET/POST/DELETE /watchlist`) sowie ein periodischer Worker, der neue Releases erkennt, fehlende Tracks via Soulseek lädt und an den SyncWorker übergibt. Konfigurierbar über `WATCHLIST_INTERVAL`.
- CI-Gates – Push/PR-Workflow führt Ruff, Black, Mypy, Pytest, Jest, TypeScript-Build und einen OpenAPI-Snapshot-Vergleich aus und sorgt damit für reproduzierbare Qualitätsprüfungen.
- Persistente Soulseek-Retries – Downloads behalten `retry_count`, `next_retry_at`, `last_error` und wechseln nach Überschreitung der Grenze in den Dead-Letter-Status. Ein neuer Retry-Scheduler re-enqueued fällige Jobs mit exponentiellem Backoff, und `/soulseek/downloads/{id}/requeue` erlaubt manuelle Neuversuche.
