# ToDo

## ✅ Erledigt
### Backend
- FastAPI-Anwendung mit Spotify-, Plex-, Soulseek-, Matching- und Settings-Routern sowie Start-/Shutdown-Handling für alle Worker steht. 【F:app/main.py†L19-L79】
- Robuste Client-Wrapper für Spotify, Plex, Soulseek und Beets inklusive Rate-Limiting, Retries und umfangreicher API-Abdeckung sind implementiert. 【F:app/core/spotify_client.py†L28-L172】【F:app/core/plex_client.py†L20-L220】【F:app/core/soulseek_client.py†L22-L182】【F:app/core/beets_client.py†L20-L200】
- Hintergrund-Worker synchronisieren Playlists, Matches, Plex-Statistiken und Soulseek-Downloads in die Datenbank. 【F:app/workers/playlist_sync_worker.py†L16-L124】【F:app/workers/matching_worker.py†L13-L73】【F:app/workers/scan_worker.py†L14-L66】【F:app/workers/sync_worker.py†L13-L123】

### Frontend
- _Keine abgeschlossenen Aufgaben._

### Tests
- Umfangreiche Pytest-Suite deckt Spotify-, Plex-, Soulseek- und Matching-Routen inklusive Worker-Verhalten ab. 【F:tests/test_spotify.py†L10-L106】【F:tests/test_plex.py†L7-L86】【F:tests/test_soulseek.py†L6-L173】【F:tests/test_matching.py†L1-L74】

### Dokumentation
- README, Architektur- und API-Dokumentation beschreiben Aufbau, Endpunkte und Worker detailliert. 【F:README.md†L1-L68】【F:docs/architecture.md†L1-L93】【F:docs/api.md†L1-L200】【F:docs/workers.md†L1-L52】

### Infrastruktur / CI
- Dockerfile, Compose-Setup und GitHub-Action zum Ausführen der Tests sind vorhanden. 【F:Dockerfile†L1-L17】【F:docker-compose.yml†L1-L13】【F:.github/workflows/autopush.yml†L1-L22】

## ⬜️ Offen
### Backend
- Beets-Router ist implementiert, aber im Hauptanwendungs-Router nicht eingebunden; die dokumentierten `/beets`-Endpunkte sind darüber aktuell nicht erreichbar. 【F:app/routers/beets_router.py†L1-L200】【F:app/main.py†L19-L29】【F:docs/api.md†L171-L199】

### Frontend
- Es existiert noch keine Benutzeroberfläche; das Projekt ist bislang ausschließlich als Backend beschrieben. 【F:README.md†L1-L24】

### Tests
- Sobald der Beets-Router global verfügbar ist, werden Integrationstests über die Haupt-App benötigt (derzeit wird der Router nur in einer Test-FastAPI-Instanz registriert). 【F:tests/test_beets.py†L10-L21】

### Dokumentation
- Dokumentation sollte aktualisiert werden, sobald die tatsächliche Erreichbarkeit der `/beets`-Routen bzw. ein zukünftiges Frontend feststehen. 【F:docs/api.md†L171-L199】【F:README.md†L1-L24】

### Infrastruktur / CI
- CI führt ausschließlich die Tests aus; statische Analysen oder Formatprüfungen fehlen noch. 【F:.github/workflows/autopush.yml†L17-L22】

## 🏁 Nächste Meilensteine
### Backend
- `/beets`-Router in `app.main` registrieren und Konfiguration/Logging an den bestehenden Dependency-Mechanismus anpassen. 【F:app/main.py†L19-L29】【F:app/routers/beets_router.py†L1-L200】

### Frontend
- Minimalen Web-Client oder Referenz-UI bereitstellen, um die APIs ohne externe Tools bedienen zu können. 【F:README.md†L1-L24】

### Tests
- End-to-End-Tests ergänzen, die nach Integration des Beets-Routers den kompletten Request-Fluss über die Hauptanwendung prüfen. 【F:tests/test_beets.py†L10-L21】

### Dokumentation
- README und API-Referenz nach Umsetzung der neuen Features (Beets-Router, Frontend) synchronisieren. 【F:docs/api.md†L171-L199】【F:README.md†L1-L68】

### Infrastruktur / CI
- Linting/Formatting (z. B. Ruff, Black) in den CI-Workflow aufnehmen, um Codequalität automatisiert sicherzustellen. 【F:.github/workflows/autopush.yml†L17-L22】
