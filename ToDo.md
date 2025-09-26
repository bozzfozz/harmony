# ToDo

## ✅ Erledigt
- **Backend**
  - FastAPI bindet alle Spotify-, Plex-, Soulseek-, Matching-, Settings-, Beets-, Search-, Sync-, System-, Download-, Activity-, Health- und Watchlist-Router ein, initialisiert die Datenbank und setzt Default-Settings beim Start.【F:app/main.py†L59-L175】
  - Der Startup-Hook startet die Artwork-, Lyrics-, Metadata-, Sync-, Matching-, Scan-, Playlist-, Watchlist-, AutoSync- und Discography-Worker und der Shutdown-Hook stoppt sie wieder sauber.【F:app/main.py†L84-L201】
  - Der SyncWorker verarbeitet Downloads mit persistenter Queue, Prioritäten-Handling, Backoff-Retrys und übergibt organisierte Dateien an das Dateisystem mittels `organize_file`.【F:app/workers/sync_worker.py†L36-L409】【F:app/utils/file_utils.py†L118-L203】
- **Frontend**
  - Das React-Frontend liefert geroutete Seiten für Dashboard, Downloads, Artists und Settings und nutzt einen Vite/TypeScript-Tooling-Stack inklusive Lint-, Test- und Build-Skripten.【F:frontend/src/App.tsx†L1-L25】【F:frontend/package.json†L1-L35】
- **Tests**
  - Die Pytest-Suite deckt u. a. Such-Filterlogik und Watchlist-Automatisierung ab und läuft vollständig grün mit 214 Tests.【F:tests/test_search.py†L39-L107】【F:tests/test_watchlist.py†L14-L141】【8a3823†L1-L34】
- **Dokumentation**
  - README und CHANGELOG dokumentieren Smart Search, Worker, Watchlist, Release-Highlights sowie die aktuellen CI-Gates konsistent zum Code-Stand.【F:README.md†L120-L168】【F:CHANGELOG.md†L1-L23】
- **Infrastruktur / CI**
  - Die CI auf Push/PR führt `ruff`, `black --check`, `mypy app`, `pytest -q`, `npm test`, `npm run typecheck`, `npm run build` sowie den OpenAPI-Snapshot-Vergleich aus.【F:.github/workflows/ci.yml†L1-L74】

## ⬜️ Offen
- **Backend**
  - FastAPI nutzt weiterhin die veralteten `@app.on_event`-Hooks für Startup/Shutdown, was Deprecation-Warnings erzeugt und auf Lifespan-Events migriert werden sollte.【F:app/main.py†L75-L201】【8a3823†L1-L34】
  - Der SyncWorker bricht nach drei Fehlversuchen endgültig ab; es fehlt eine langfristige Retry-/Escalation-Strategie für hartnäckige Downloads.【F:app/workers/sync_worker.py†L41-L409】
- **Tests**
  - Der Testlauf produziert wiederkehrende Deprecation-Warnings, die das Rauschen in der Pipeline erhöhen.【8a3823†L1-L34】

## 🏁 Nächste Meilensteine
- **Backend**
  - Startup/Shutdown auf FastAPI-Lifespan umstellen und Warnungen eliminieren, inklusive Testabdeckung der Worker-Lifecycle-Logik.【F:app/main.py†L75-L201】【8a3823†L1-L34】
  - Download-Retry-Mechanismus erweitern (z. B. Exponential Backoff mit Persistenz oder Übergabe an AutoSync), um mehr als drei Fehlversuche robust zu handhaben.【F:app/workers/sync_worker.py†L41-L409】
- **Tests**
  - Deprecation-Warnings adressieren oder `-W error` aktivieren, um die Suite warning-frei zu halten.【8a3823†L1-L34】
