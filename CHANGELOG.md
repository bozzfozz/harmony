# Changelog

Alle Änderungen an diesem Projekt werden in diesem Dokument festgehalten. Dieses Changelog folgt dem [Keep a Changelog](https://keepachangelog.com/de/1.1.0/) Format und verwendet [SemVer](https://semver.org/lang/de/).

## [Unreleased]
### Added
- Noch keine Einträge.

### Changed
- Noch keine Einträge.

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
