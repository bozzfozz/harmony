# ToDo

## ✅ Erledigt
- **Backend**
  - FastAPI bindet alle Spotify-, Plex-, Soulseek-, Matching-, Settings-, Beets-, Search-, Sync-, System-, Download-, Activity-, Health- und Watchlist-Router ein, initialisiert die Datenbank und setzt Default-Settings beim Start.【F:app/main.py†L60-L177】
  - Der Startup-Hook startet die Artwork-, Lyrics-, Metadata-, Sync-, Matching-, Scan-, Playlist-, Watchlist-, AutoSync- und Discography-Worker und der Shutdown-Hook stoppt sie wieder sauber.【F:app/main.py†L76-L208】
  - Der SyncWorker verarbeitet Downloads mit persistenter Queue, Prioritäten-Handling, Backoff-Retrys und übergibt organisierte Dateien an das Dateisystem mittels `organize_file`.【F:app/workers/sync_worker.py†L36-L430】【F:app/utils/file_utils.py†L114-L191】
  - Persistente Soulseek-Retries mit Dead-Letter-Queue, Scheduler und manuellem `/soulseek/downloads/{id}/requeue`-Endpoint halten problematische Downloads sichtbar und planen Neuversuche automatisch.【F:app/workers/sync_worker.py†L36-L620】【F:app/workers/retry_scheduler.py†L1-L207】【F:app/routers/soulseek_router.py†L1-L498】
  - Spotify FREE-Modus mit Modusschalter, Parser und Enqueue (`/spotify/mode`, `/spotify/free/*`) inkl. Settings-Limits und FLAC-Priorisierung.【F:app/routers/spotify_router.py†L27-L55】【F:app/routers/spotify_free_router.py†L1-L357】【F:app/config.py†L15-L120】
  - Spotify PRO Backfill ergänzt FREE-Ingest-Datensätze via `/spotify/backfill/run` und Job-Monitoring (`/spotify/backfill/jobs/{id}`), nutzt `backfill_jobs`/`spotify_cache`, enriches IDs/ISRC/Dauer und expandiert registrierte Playlist-Links.【F:app/services/backfill_service.py†L1-L388】【F:app/routers/backfill_router.py†L1-L132】【F:app/main.py†L28-L205】
  - Spotify Ingest Pipeline: FREE/PRO teilen sich Job-/Item-States, Backpressure & Chunking (`INGEST_BATCH_SIZE`, `INGEST_MAX_PENDING_JOBS`), loggen Normalisierung/Enqueue, liefern strukturierte `accepted`/`skipped`/`error`-Antworten und aktualisieren Worker-States; Tests decken Multi-Status/Limit-Fälle ab.【F:app/config.py†L81-L119】【F:app/services/free_ingest_service.py†L121-L647】【F:app/routers/free_ingest_router.py†L50-L171】【F:app/workers/sync_worker.py†L451-L856】【F:tests/test_free_ingest_router.py†L17-L117】
  - FREE Ingest URL Validation: `/imports/free` akzeptiert bis zu 1 000 Playlist-Links, validiert/normalisiert IDs, legt Import-Sessions & Batches an und liefert akzeptierte, übersprungene und abgelehnte Links zurück.【F:app/routers/imports_router.py†L1-L152】【F:app/utils/spotify_free.py†L1-L198】【F:app/models.py†L129-L170】
  - Artwork-Pipeline cached Spotify- und MusicBrainz/CAA-Cover pro Album, erkennt Low-Res-Embeds anhand konfigurierbarer Grenzen und ersetzt nur dann; neue ENV-Flags steuern Timeouts, Concurrency sowie den optionalen `beet write`/`beet update`-Poststep.【F:app/workers/artwork_worker.py†L1-L814】【F:app/utils/artwork_utils.py†L1-L420】【F:app/config.py†L30-L200】
  - Plex-Integration auf Matching & Scans verschlankt (`/plex/status`, `/plex/libraries`, `/plex/library/{id}/scan`, `/plex/search`, `/plex/tracks`) inklusive deduplizierter Scan-Requests und aktualisierter Tests/Dokumentation.【F:app/routers/plex_router.py†L1-L186】【F:app/core/plex_client.py†L1-L299】【F:tests/test_plex_router.py†L1-L130】
- **Frontend**
  - Das React-Frontend liefert geroutete Seiten für Dashboard, Downloads, Artists und Settings und nutzt einen Vite/TypeScript-Tooling-Stack inklusive Lint-, Test- und Build-Skripten.【F:frontend/src/App.tsx†L1-L25】【F:frontend/package.json†L1-L35】
  - Spotify-Seite mit FREE-Import-Karte (Textarea, Upload, Vorschau, Enqueue) sowie Modus-Schalter im Settings-Tab.【F:frontend/src/pages/SpotifyPage.tsx†L1-L79】【F:frontend/src/components/SpotifyFreeImport.tsx†L1-L187】【F:frontend/src/pages/SettingsPage.tsx†L1-L210】
- **Tests**
  - Die Pytest-Suite deckt u. a. Such-Filterlogik und Watchlist-Automatisierung ab und läuft vollständig grün mit 214 Tests.【F:tests/test_search.py†L39-L107】【F:tests/test_watchlist.py†L14-L141】【8a3823†L1-L34】
- **Dokumentation**
  - README und CHANGELOG dokumentieren Smart Search, Worker, Watchlist, Release-Highlights sowie die aktuellen CI-Gates konsistent zum Code-Stand.【F:README.md†L101-L172】【F:CHANGELOG.md†L1-L18】
- **Suche**
  - Smart Search erhielt strukturierte Filter (Genre, Jahr, Qualität) inkl. Normalisierung, Ranking-Boosts und aktualisierte API-Dokumentation.【F:app/routers/search_router.py†L1-L280】【F:docs/api.md†L130-L233】
- **Infrastruktur / CI**
  - Die CI auf Push/PR führt `ruff`, `black --check`, `mypy app`, `pytest -q`, `npm test`, `npm run typecheck`, `npm run build` sowie den OpenAPI-Snapshot-Vergleich aus.【F:.github/workflows/ci.yml†L1-L74】

## ⬜️ Offen
- **Backend**
  - FastAPI nutzt weiterhin die veralteten `@app.on_event`-Hooks für Startup/Shutdown, was Deprecation-Warnings erzeugt und auf Lifespan-Events migriert werden sollte.【F:app/main.py†L75-L201】【8a3823†L1-L34】
-  - DLQ-Einträge benötigen langfristig UI/Management (Filter, Retry, Cleanup) und Monitoring-Kennzahlen.【F:app/routers/soulseek_router.py†L180-L225】
- **Tests**
  - Der Testlauf produziert wiederkehrende Deprecation-Warnings, die das Rauschen in der Pipeline erhöhen.【8a3823†L1-L34】

## 🏁 Nächste Meilensteine
- **Backend**
  - Startup/Shutdown auf FastAPI-Lifespan umstellen und Warnungen eliminieren, inklusive Testabdeckung der Worker-Lifecycle-Logik.【F:app/main.py†L75-L201】【8a3823†L1-L34】
  - DLQ-Downloads im Frontend visualisieren und steuerbar machen (bulk requeue, purge) inkl. Monitoring von Retry-Metriken.【F:app/workers/retry_scheduler.py†L1-L207】
- **Tests**
  - Deprecation-Warnings adressieren oder `-W error` aktivieren, um die Suite warning-frei zu halten.【8a3823†L1-L34】
