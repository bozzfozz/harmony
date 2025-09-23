# Changelog

## [Unreleased]

### Changed
- CI priorisiert nun die Backend-Tests (`pytest`); Frontend-Tests werden aufgrund fehlenden npm-Registry-Zugriffs übersprungen.

### Added
- Systemstatus-Endpunkte (`/status`, `/api/system/stats`) für das FastAPI-Backend inklusive Worker-Überblick und psutil-basierter Systemmetriken.
- Dokumentation und Tests für die neuen System-Routen.
- API-Routen für das Metadaten-Handling (`/api/metadata/*`) inklusive neuem `MetadataUpdateWorker`.
- Tests, Dokumentation und Shutdown-Handling für den Metadaten-Workflow.
- Sync- und Such-Endpunkte (`/api/sync`, `/api/search`) mit Anbindung an bestehende Worker und Multi-Service-Suche.
- Zusätzliche Tests und Dokumentation für Sync- und Search-APIs.
- Download-Management über `/api/download` mit Persistenz, Worker-Anbindung und Unit-Tests.
- Aktivitätsfeed `/api/activity` mit In-Memory-Verwaltung, Integrationspunkten und Tests.
- Frontend-Downloads-Seite mit Formular zum Starten neuer Transfers, Polling-Tabelle und Fehler-Handling.
- Dashboard-Widget für den Aktivitätsfeed inklusive automatischem Polling und Toast-Benachrichtigungen.
