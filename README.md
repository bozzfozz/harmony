# Harmony Backend

Harmony ist ein FastAPI-Backend, das Spotify, Plex, Soulseek (slskd), Beets sowie eine eigene Matching-Engine und Hintergrund-Worker
zu einem gemeinsamen Musik-Hub kombiniert. Die Anwendung bündelt Bibliotheken, Downloads und Metadaten, synchronisiert sie zyklisch
und stellt einheitliche JSON-APIs für Automatisierungen und Frontend-Clients bereit.

## Features

- **Vollständige Spotify-Integration** für Suche, Playlists, Audio-Features, Empfehlungen und Benutzerbibliotheken.
- **Async Plex-Client** mit Zugriff auf Bibliotheken, Sessions, PlayQueues, Live-TV und Echtzeit-Benachrichtigungen.
- **Soulseek-Anbindung** inklusive Download-/Upload-Verwaltung, Warteschlangen und Benutzerinformationen.
- **Beets CLI Bridge** zum Importieren, Aktualisieren, Verschieben und Abfragen der lokalen Musikbibliothek.
- **Matching-Engine** zur Ermittlung der besten Kandidaten zwischen Spotify ↔ Plex/Soulseek inklusive Persistierung.
- **SQLite-Datenbank** mit SQLAlchemy-Modellen für Playlists, Downloads, Matches und Settings.
- **Hintergrund-Worker** für Soulseek-Synchronisation, Matching-Queue, Plex-Scans und Spotify-Playlist-Sync.
- **Docker & GitHub Actions** für reproduzierbare Builds, Tests und Continuous Integration.

## Architekturüberblick

Harmony folgt einer klar getrennten Schichten-Architektur:

- **Core**: Enthält API-Clients (`spotify_client.py`, `plex_client.py`, `soulseek_client.py`, `beets_client.py`) und die Matching-Engine.
- **Routers**: FastAPI-Router kapseln die öffentlich erreichbaren Endpunkte (Spotify, Plex, Soulseek, Matching, Settings, Beets).
- **Workers**: Asynchrone Tasks synchronisieren Playlists, Soulseek-Downloads, Plex-Statistiken und Matching-Jobs.
- **Datenbank-Layer**: `app/db.py`, SQLAlchemy-Modelle und -Schemas verwalten persistente Zustände.

Eine ausführliche Beschreibung der Komponenten findest du in [`docs/architecture.md`](docs/architecture.md).

## Setup-Anleitung

### Voraussetzungen

- Python 3.11
- SQLite (im Lieferumfang enthalten)
- Optional: Docker und Docker Compose

### Lokales Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Konfiguriere erforderliche Umgebungsvariablen (siehe Tabelle unten), bevor du den Server startest.

### Docker

```bash
docker build -t harmony-backend .
docker run --env-file .env -p 8000:8000 harmony-backend
```

### Docker Compose

```bash
docker compose up --build
```

Das Dev-Override (`docker-compose.override.yml`) aktiviert Hot-Reloading und Debug-Logging.

### GitHub Actions

Der Workflow [`.github/workflows/autopush.yml`](.github/workflows/autopush.yml) führt bei jedem Push auf `main` sowie bei Pull
Requests die Test-Suite (`pytest`) unter Python 3.11 aus.

## Konfiguration

| Variable | Beschreibung |
| --- | --- |
| `SPOTIFY_CLIENT_ID` | Spotify OAuth Client ID |
| `SPOTIFY_CLIENT_SECRET` | Spotify OAuth Client Secret |
| `SPOTIFY_REDIRECT_URI` | Redirect URI für den OAuth-Flow |
| `SPOTIFY_SCOPE` | Optionaler Scope für Spotify Berechtigungen |
| `PLEX_BASE_URL` | Basis-URL des Plex-Servers |
| `PLEX_TOKEN` | Plex Auth Token |
| `PLEX_LIBRARY` | Name der Plex-Musikbibliothek |
| `SLSKD_URL` | Basis-URL des Soulseek-Daemons |
| `SLSKD_API_KEY` | API-Key für slskd (falls gesetzt) |
| `DATABASE_URL` | SQLAlchemy Verbindungsstring (Standard: `sqlite:///./harmony.db`) |
| `HARMONY_LOG_LEVEL` | Log-Level (`INFO`, `DEBUG`, …) |
| `HARMONY_DISABLE_WORKERS` | `1` deaktiviert alle Hintergrund-Worker (z. B. für Tests) |

> **Hinweis:** Spotify-, Plex- und slskd-Zugangsdaten können über den `/settings`-Endpoint gepflegt und in der Datenbank persistiert werden. Beim Laden der Anwendung haben Werte aus der Datenbank Vorrang vor Umgebungsvariablen; letztere dienen weiterhin als Fallback.

## API-Endpoints

Eine vollständige Referenz der FastAPI-Routen befindet sich in [`docs/api.md`](docs/api.md). Die wichtigsten Gruppen im Überblick:

- **Spotify** (`/spotify`): Status, Suche, Track-Details, Audio-Features, Benutzerbibliothek, Playlists, Empfehlungen.
- **Plex** (`/plex`): Status & Statistiken, Bibliotheken, PlayQueues, Playlists, Timeline, Bewertungen, Benachrichtigungen.
- **Soulseek** (`/soulseek`): Status, Suche, Downloads/Uploads, Warteschlangen, Benutzerverzeichnisse und -infos.
- **Matching** (`/matching`): Spotify→Plex, Spotify→Soulseek sowie Album-Matching.
- **Settings** (`/settings`): Key-Value Einstellungen inkl. History.
- **Beets** (`/beets`): Import, Update, Query, Stats und Dateimanipulation via CLI.

## Tests & CI

```bash
pytest
```

Die Tests mocken externe Dienste und können lokal wie auch via GitHub Actions ausgeführt werden. Für deterministische
Runs sollten die Worker mit `HARMONY_DISABLE_WORKERS=1` deaktiviert werden.

## Lizenz

Das Projekt steht derzeit ohne explizite Lizenzdatei zur Verfügung. Ohne eine veröffentlichte Lizenz gelten sämtliche Rechte
als vorbehalten.
