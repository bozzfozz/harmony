# ToDo

- [x] Systemstatus- und Monitoring-Endpunkte in FastAPI übernehmen.
- [x] Metadaten-Workflow für Dashboard-Portierung abschließen.
- [x] Sync- und Suchfunktionen zwischen Spotify/Plex/Soulseek vereinheitlichen.
- [x] Download-Management via `/api/download` inkl. Worker-Integration fertigstellen.
- [x] Aktivitätsfeed `/api/activity` als In-Memory-Queue bereitstellen.
- [x] Downloads-Frontend mit Tabelle und Start-Formular bereitstellen.
- [x] GET-Endpunkte für Downloads (`/api/downloads`, `/api/download/{id}`) ergänzen.
- [x] Activity-Feed-Widget im Dashboard mit Polling, Sortierung und Status-Badges finalisieren.
- [x] AutoSyncWorker für Spotify↔Plex implementieren, Soulseek/Beets-Anbindung ergänzen und Dokumentation aktualisieren.
- [x] Artist-Konfiguration für Spotify-Releases (API, DB, AutoSync) umsetzen.
- [x] Artists-Frontend zum Aktivieren einzelner Releases inkl. Tests und Dokumentation ergänzen.
- [ ] Streaming-Router für Audio-Features planen und implementieren (Frontend-Integration vorbereiten).
- [ ] Frontend-Testlauf im CI wieder aktivieren, sobald npm-Registry-Zugriff verfügbar ist.
- [ ] Prometheus-/StatsD-Exporter auf Basis der neuen `metrics.*` Settings anbinden.
