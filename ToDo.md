# ToDo

## ✅ Erledigt
- **Backend**
  - FastAPI bindet die aktiven Router (`/spotify`, `/soulseek`, `/matching`, `/settings`, `/search`, `/sync`, `/system`, `/download`, `/activity`, `/health`, `/watchlist`) ein, initialisiert die Datenbank und setzt Default-Settings im Lifespan-Hook. Archivierte Plex/Beets-Routen werden nicht registriert.【F:app/main.py†L248-L268】
  - Der Lifespan-Handler startet Artwork-, Lyrics-, Metadata-, Sync-, Matching-, Playlist-, Watchlist- und Retry-Worker und stoppt sie über die zentralisierte Shutdown-Routine wieder sauber. Plex/Beets-abhängige Worker bleiben deaktiviert.【F:app/main.py†L94-L214】
  - Der SyncWorker verarbeitet Downloads mit persistenter Queue, Prioritäten-Handling, Backoff-Retrys und übergibt organisierte Dateien an das Dateisystem mittels `organize_file`.【F:app/workers/sync_worker.py†L36-L430】【F:app/utils/file_utils.py†L114-L191】
  - Persistente Soulseek-Retries mit Dead-Letter-Queue, Scheduler und manuellem `/soulseek/downloads/{id}/requeue`-Endpoint halten problematische Downloads sichtbar und planen Neuversuche automatisch.【F:app/workers/sync_worker.py†L36-L620】【F:app/workers/retry_scheduler.py†L1-L207】【F:app/routers/soulseek_router.py†L1-L498】
  - Spotify FREE-Modus mit Modusschalter, Parser und Enqueue (`/spotify/mode`, `/spotify/free/*`) inkl. Settings-Limits und FLAC-Priorisierung.【F:app/routers/spotify_router.py†L27-L55】【F:app/routers/spotify_free_router.py†L1-L357】【F:app/config.py†L15-L120】
  - Spotify PRO Backfill ergänzt FREE-Ingest-Datensätze via `/spotify/backfill/run` und Job-Monitoring (`/spotify/backfill/jobs/{id}`), nutzt `backfill_jobs`/`spotify_cache`, enriches IDs/ISRC/Dauer und expandiert registrierte Playlist-Links.【F:app/services/backfill_service.py†L1-L388】【F:app/routers/backfill_router.py†L1-L132】【F:app/main.py†L28-L205】
  - Spotify Ingest Pipeline: FREE/PRO teilen sich Job-/Item-States, Backpressure & Chunking (`INGEST_BATCH_SIZE`, `INGEST_MAX_PENDING_JOBS`), loggen Normalisierung/Enqueue, liefern strukturierte `accepted`/`skipped`/`error`-Antworten und aktualisieren Worker-States; Tests decken Multi-Status/Limit-Fälle ab.【F:app/config.py†L81-L119】【F:app/services/free_ingest_service.py†L121-L647】【F:app/routers/free_ingest_router.py†L50-L171】【F:app/workers/sync_worker.py†L451-L856】【F:tests/test_free_ingest_router.py†L17-L117】
  - FREE-Ingest Jobs bewahren Partial-Fehlertexte trotz gleichzeitiger Skips und liefern ergänzende Skip-Metadaten im Status-Endpoint.【F:app/services/free_ingest_service.py†L210-L315】【F:app/services/free_ingest_service.py†L585-L649】【F:app/routers/free_ingest_router.py†L78-L258】
  - FREE Ingest URL Validation: `/imports/free` akzeptiert bis zu 1 000 Playlist-Links, validiert/normalisiert IDs, legt Import-Sessions & Batches an und liefert akzeptierte, übersprungene und abgelehnte Links zurück.【F:app/routers/imports_router.py†L1-L152】【F:app/utils/spotify_free.py†L1-L198】【F:app/models.py†L129-L170】
  - Artwork-Pipeline cached Spotify- und MusicBrainz/CAA-Cover pro Album, erkennt Low-Res-Embeds anhand konfigurierbarer Grenzen und ersetzt nur dann; neue ENV-Flags steuern Timeouts & Concurrency, der frühere `beet write`/`beet update`-Poststep ist archiviert.【F:app/workers/artwork_worker.py†L1-L814】【F:app/utils/artwork_utils.py†L1-L420】【F:app/config.py†L30-L200】
  - Plex- und Beets-Integrationen sind im MVP archiviert; Health-Check und Matching-Routen signalisieren `disabled`/`503`, der Quellcode liegt unter `archive/integrations/plex_beets/` für eine spätere Reaktivierung.【F:app/main.py†L248-L268】【F:app/routers/health_router.py†L19-L33】【F:archive/integrations/plex_beets/README.md†L1-L12】
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
  - Die CI auf Push/PR führt `ruff`, `black --check`, `mypy app`, `pytest -q`, `npm test`, `npm run typecheck`, `npm run build` sowie den OpenAPI-Snapshot-Vergleich aus.【F:.github/workflows/ci.yml†L1-L95】
  - Black ist auf Version 24.8.0 gepinnt und nutzt die gemeinsame `pyproject.toml`-Konfiguration für reproduzierbare Formatierungsläufe.【F:.github/workflows/ci.yml†L26-L35】【F:pyproject.toml†L1-L14】
  - Bandit, Radon, Vulture und pip-audit sind als Dev-Abhängigkeiten verfügbar, per Makefile lokal aufrufbar und in der CI als verpflichtende Gates integriert; Offline-Umgebungen können die Security- und Analyse-Ziele über `CI_OFFLINE=true` gezielt überspringen.【F:requirements-dev.txt†L1-L4】【F:Makefile†L1-L36】【F:.github/workflows/ci.yml†L20-L69】【F:README.md†L196-L205】
  - `scripts/audit_wiring.py` prüft, dass keine Plex/Beets-Referenzen im aktiven Code landen, und läuft als eigener CI-Schritt.【F:scripts/audit_wiring.py†L1-L87】【F:.github/workflows/ci.yml†L20-L38】

## ⬜️ Offen
- **Backend**
  - DLQ-Einträge benötigen langfristig UI/Management (Filter, Retry, Cleanup) und Monitoring-Kennzahlen.【F:app/routers/soulseek_router.py†L180-L225】
  - Watchlist-Worker auf blockierende API-Calls prüfen und bei Bedarf via `asyncio.to_thread` oder dedizierte Executor kapseln.【F:app/workers/watchlist_worker.py†L101-L210】
- **Tests**
  - Der neue Lifespan-Pfad benötigt ergänzende Tests, die Start-/Stop-Orchestrierung und fehlertolerantes Verhalten der Worker absichern.【F:app/main.py†L95-L214】【F:tests/simple_client.py†L1-L87】

## 🏁 Nächste Meilensteine
- **Backend**
  - Worker-Lifecycle im FastAPI-Lifespan mit gezielten Tests absichern (z. B. Fehlerpfade, wiederholte Starts).【F:app/main.py†L95-L214】【F:tests/simple_client.py†L1-L87】
  - DLQ-Downloads im Frontend visualisieren und steuerbar machen (bulk requeue, purge) inkl. Monitoring von Retry-Metriken.【F:app/workers/retry_scheduler.py†L1-L207】
  - **Tests**
    - Suite läuft warning-frei; prüfen, ob `-W error` aktiviert werden kann, um Regressionen künftig sofort zu bremsen.【09fe8d†L1-L2】
