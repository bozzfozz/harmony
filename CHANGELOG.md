# Changelog

# v1.x.x
- Vollständige slskd API-Integration (Transfers & Users).

# v1.4.0
- Vollständige Plex-Integration auf Basis der offiziellen API (aiohttp, async).
- Neue API-Endpunkte für Bibliotheken, Status, Playback, Playlists, Playqueues und Bewertungen.
- Unterstützung für Echtzeit-Benachrichtigungen, Geräte- & Live-TV-Übersichten sowie Tag-Synchronisierung.

## v1.3.0
- Spotify-Playlists werden alle 15 Minuten synchronisiert und in der Datenbank gespeichert.
- Neuer API-Endpunkt `/spotify/playlists` liefert die persistierten Playlists inklusive Track-Anzahl.

## v1.2.0
- Soulseek-Downloads werden mit Status, Fortschritt und Zeitstempeln in der Datenbank gespeichert.
- Sync-Worker pollt den Soulseek-Client zyklisch und aktualisiert Downloadzustände zuverlässig.
- Soulseek-API liefert Fortschrittsinformationen aus der Datenbank und unterstützt Abbrüche mit Status `failed`.

## v1.1.0
- Beets-Integration: CLI-Anbindung zum Importieren, Aktualisieren und Abfragen der Bibliothek.
- Dockerfile: Standardstartbefehl für Production (`uvicorn app.main:app`)
- docker-compose.yml: verschlankt, keine Command-Definition mehr
- docker-compose.override.yml: Dev-Setup mit `--reload` und Debug-Loglevel

## v1.0.0
- Initiale Version des Harmony-Backends mit FastAPI, SQLite und vollständiger Testabdeckung.
