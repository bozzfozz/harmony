# Changelog

## [Unreleased]

### Added
- Systemstatus-Endpunkte (`/status`, `/api/system/stats`) für das FastAPI-Backend inklusive Worker-Überblick und psutil-basierter Systemmetriken.
- Dokumentation und Tests für die neuen System-Routen.
- API-Routen für das Metadaten-Handling (`/api/metadata/*`) inklusive neuem `MetadataUpdateWorker`.
- Tests, Dokumentation und Shutdown-Handling für den Metadaten-Workflow.
- Sync- und Such-Endpunkte (`/api/sync`, `/api/search`) mit Anbindung an bestehende Worker und Multi-Service-Suche.
- Zusätzliche Tests und Dokumentation für Sync- und Search-APIs.
