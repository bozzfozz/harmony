# Changelog

## v1.3.0
- Spotify-Playlists werden alle 15 Minuten synchronisiert und in der Datenbank gespeichert.
- Neuer API-Endpunkt `/spotify/playlists` liefert die persistierten Playlists inklusive Track-Anzahl.

## v1.2.0
- Soulseek-Downloads werden mit Status, Fortschritt und Zeitstempeln in der Datenbank gespeichert.
- Sync-Worker pollt den Soulseek-Client zyklisch und aktualisiert Downloadzustände zuverlässig.
- Soulseek-API liefert Fortschrittsinformationen aus der Datenbank und unterstützt Abbrüche mit Status `failed`.

## v1.1.0
- Dockerfile: Standardstartbefehl für Production (`uvicorn app.main:app`)
- docker-compose.yml: verschlankt, keine Command-Definition mehr
- docker-compose.override.yml: Dev-Setup mit `--reload` und Debug-Loglevel

## v1.0.0
- Initiale Version des Harmony-Backends mit FastAPI, SQLite und vollständiger Testabdeckung.
