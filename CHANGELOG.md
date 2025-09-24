# Changelog

Alle Änderungen an diesem Projekt werden in diesem Dokument festgehalten. Dieses Changelog folgt dem [Keep a Changelog](https://keepachangelog.com/de/1.1.0/) Format und verwendet [SemVer](https://semver.org/lang/de/).

## [Unreleased]
### Added
- AutoSync-, Sync- und Download-Aufrufe prüfen jetzt Credentials und erzeugen bei fehlender Konfiguration `*_blocked`-Events (inkl. 503-Antworten und UI-Toasts).
- Improved Download Flow (auto-retry, priority queueing, status filters).
- Added download export endpoint (CSV/JSON) with filters.
- Frontend: Enhanced DownloadsPage with filters, priority controls and export buttons.
- Frontend: Download widget now shows priorities and only active transfers.
- Added Activity History export (CSV/JSON).
- Frontend: Added export for Activity History.
- Added worker health events (started/stopped/stale/restarted) to the Activity Feed.
- Frontend: ActivityFeed widget shows worker health indicators with icons and colours.
- Frontend: ActivityFeed widget shows detailed sync/search events.
- Frontend: Added Worker Health cards to Dashboard.
- Added health endpoints `/api/health/{spotify|plex|soulseek}` to validate stored credentials.
- `/status` exposes aggregated connection status for Spotify, Plex and Soulseek.
- Frontend: Service-Verbindungen-Karte auf dem Dashboard mit ✅/❌-Indikatoren.
- Frontend: Settings-Seite mit Verbindungstest-Buttons für Spotify, Plex und Soulseek.
- Added worker health info (heartbeats + queue size) to `/status`.
- Added automatic defaults for worker-related settings at startup.
- Added persistent Activity Feed with flexible event types.
- Added persistent Activity History with paging & filters.
- Frontend: Added Activity History page with paging and filters.
- Frontend: Cancel-/Retry-Buttons für Downloads (Downloads-Seite & Dashboard-Widget).
- Added cancel and retry endpoints for downloads via slskd TransfersApi.
- Added limit/offset support to GET /api/downloads.
- Added DownloadWidget to Dashboard.
- Added GET endpoints for downloads.
- Frontend-Downloads-Seite mit Start-Formular, Fortschrittsanzeige und Zeitstempeln.
- Dokumentation des Endpunkts `GET /api/download` inkl. Response-Beispiel.
- AutoSyncWorker, der Spotify-Playlists und gespeicherte Tracks automatisch mit Plex abgleicht, fehlende Titel via Soulseek lädt und anschließend per Beets importiert (manuell triggerbar über `/api/sync`).
- Artist-Konfiguration mit neuen Spotify- und Settings-Endpunkten sowie der Tabelle `artist_preferences`.
- Artists-Seite im Frontend zur Verwaltung gefolgter Spotify-Artists und ihrer Releases inklusive Sync-Toggles.
- Persistente Worker-Queues (`worker_jobs`) inkl. Health/Metric-Tracking (`worker.*`, `metrics.*`) für Sync-, Matching- und Scan-Worker.
- Quality-/Priorisierungsregeln für den AutoSyncWorker (`autosync_min_bitrate`, `autosync_preferred_formats`, Skip-State in `auto_sync_skipped_tracks`).
- Added optional persistence for album matching (`persist=true` on `/matching/spotify-to-plex-album`).
- Datenbankindizes für Downloads (Status, Erstellung) und Activity-Events (Typ, Status, Timestamp) zur Beschleunigung von Abfragen.
- E2E-Smoke-Test verifiziert den vollständigen Download-Flow (API, Persistenz, Activity Feed) mit Worker-Stubs.

### Changed
- Soulseek-Konfiguration vereinheitlicht: `SLSKD_URL` ist die maßgebliche Einstellung; Legacy-Varianten werden automatisch als URL übernommen.
- Download-Router nutzt ausgelagerte Utility-Funktionen für Statusfilter, Prioritäten und CSV-Exporte, um Wartung und Tests zu vereinfachen.
- Aktivitäts-Event-Status wurden in `app/utils/events.py` zentralisiert und in Routern, Workern sowie Tests referenziert.
- SyncWorker- und AutoSyncWorker-Shutdowns brechen ausstehende Retry-Tasks kontrolliert ab und loggen verbleibende Pending-Jobs.
- PATCH `/api/download/{id}/priority` synchronises worker job priorities and reschedules queued/retrying tasks.
- Download widgets filter out completed/cancelled items and expose priority labels.
- Frontend: DownloadsPage nutzt jetzt `GET /api/downloads` für die Download-Übersicht.
- Dashboard-Aktivitätsfeed mit lokalisierten Typen, sortierten Einträgen und farbcodierten Status-Badges verfeinert.
- AutoSyncWorker filtert Spotify-Tracks anhand gespeicherter Artist-Präferenzen.
- SyncWorker parallelisiert Downloads und passt das Polling adaptiv an inaktive Phasen an.
- Settings-Formulare maskieren nun sensible Eingaben (Secrets/Tokens) und zeigen Health-Rückmeldungen an.
- MatchingWorker verarbeitet Jobs in Batches, speichert mehrere Treffer oberhalb des Confidence-Thresholds und schreibt Kennzahlen.
- ScanWorker liest Intervall-/Incremental-Settings, löst optionale Plex-Incremental-Scans aus und meldet wiederholte Fehler im Activity Feed.

### Fixed
- Noch keine Einträge.

### Removed
- Noch keine Einträge.

## [0.5.0] - 2025-09-23
### Added
- Systemstatus-API `GET /status` und Monitoring-Endpunkt `GET /api/system/stats` mit psutil-basierten Kennzahlen.
- Metadaten-API `GET/POST /api/metadata/*` inklusive `MetadataUpdateWorker` für orchestrierte Aktualisierungen.
- Synchronisations- und Suchschnittstellen `POST /api/sync` und `GET /api/search` für plattformübergreifende Abgleiche.
- Downloadmanagement über `POST /api/download` mit persistenter Queue und Worker-Anbindung.
- Aktivitätsfeed `GET /api/activity` mit In-Memory-Queue zur Laufzeitüberwachung.
- Frontend-Ansicht für Downloads zum Starten und Überwachen neuer Transfers.
- Dashboard-Widget für den Aktivitätsfeed mit automatischem Polling und Toast-Benachrichtigungen.

### Changed
- Dokumentation und Tests der System-, Metadaten-, Sync- und Search-Endpunkte erweitert.
- Shutdown-Handling des `MetadataUpdateWorker` zur Stabilisierung der Warteschlangen verbessert.

### Fixed
- Noch keine Einträge.

### Removed
- Noch keine Einträge.

## [0.4.0] - 2025-05-10
### Added
- React-basierte Harmony Web UI mit Dashboard, Service-Tabs sowie Dark-/Light-Mode.
- Konsolidierte REST-APIs für Spotify, Plex, Soulseek, Matching, Settings und Beets.
- Asynchrone Worker für Spotify-Playlist-Sync, Soulseek-Downloads und Plex-Statistiken.
- Docker-Setup und GitHub-Actions-Pipelines für reproduzierbare Builds und Tests.

### Changed
- Datenbankschemata zur Unterstützung der Matching-Engine konsolidiert.
- README und Architektur-Dokumentation auf die neue Web UI abgestimmt.

### Fixed
- Robustere Fehlerbehandlung für Soulseek-Warteschlangen zur Stabilisierung der Queue.

### Removed
- Noch keine Einträge.

## [0.1.0] - 2024-01-15
### Added
- FastAPI-Backend mit Integrationen für Spotify, Plex, Soulseek und Beets.
- SQLAlchemy-Modelle für Playlists, Downloads, Matches und Settings.
- Hintergrund-Worker für Synchronisation und Matching.
- Basis-Dokumentation für Setup, Konfiguration und API-Endpunkte.

### Changed
- Noch keine Einträge.

### Fixed
- Noch keine Einträge.

### Removed
- Noch keine Einträge.
