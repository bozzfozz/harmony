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

<!--
Template für neue Releases:

## [X.Y.Z] - YYYY-MM-DD
### Added
-

### Changed
-

### Fixed
-

### Removed
-
-->

## [0.5.0] - 2024-09-23
### Added
- Systemstatus- und Monitoring-Endpunkte (`/status`, `/api/system/stats`) mit psutil-basierten Kennzahlen.
- Metadaten-Routen (`/api/metadata/*`) samt `MetadataUpdateWorker` für orchestrierte Aktualisierungen.
- Sync- und Such-APIs (`/api/sync`, `/api/search`) für plattformübergreifende Abgleiche.
- Downloadverwaltung über `/api/download` inklusive Persistenz und Worker-Anbindung.
- Aktivitätsfeed-Endpunkt (`/api/activity`) mit In-Memory-Queue für laufende Jobs.
- Frontend-Downloads-Ansicht zum Starten und Überwachen neuer Transfers.
- Dashboard-Widget für den Aktivitätsfeed mit automatischem Polling und Toast-Hinweisen.

### Changed
- Dokumentation und Tests für System-, Metadaten-, Sync- und Search-Endpunkte erweitert.
- Shutdown-Handling der Metadaten-Worker verbessert.

### Fixed
- Noch keine Einträge.

### Removed
- Noch keine Einträge.

## [0.4.0] - 2024-05-10
### Added
- React-basierte Harmony Web UI mit Dashboard, Service-Tabs und Dark-/Light-Mode.
- Einheitliche REST-Endpunkte für Spotify, Plex, Soulseek, Matching, Settings und Beets.
- Async Worker für Spotify-Playlist-Sync, Soulseek-Downloads und Plex-Statistiken.
- Docker- und GitHub-Actions-Setups für reproduzierbare Builds und Tests.

### Changed
- Datenbank-Schemata zur Unterstützung der Matching-Engine konsolidiert.
- README und Architektur-Dokumentation zur neuen Web UI aktualisiert.

### Fixed
- Stabilität der Soulseek-Warteschlangen durch robustere Fehlerbehandlung verbessert.

### Removed
- Noch keine Einträge.

## [0.1.0] - 2023-08-01
### Added
- Initiales FastAPI-Backend mit Spotify-, Plex-, Soulseek- und Beets-Integrationen.
- SQLAlchemy-Modelle für Playlists, Downloads, Matches und Settings.
- Grundlegende Hintergrund-Worker für Synchronisation und Matching.
- Basis-Dokumentation für Setup, Konfiguration und API-Endpunkte.

### Changed
- Noch keine Einträge.

### Fixed
- Noch keine Einträge.

### Removed
- Noch keine Einträge.
