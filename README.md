# Harmony Backend

Harmony ist ein FastAPI-Backend, das Spotify, Plex und den Soulseek-Daemon (slskd) integriert und eine Matching-Engine für Musikbibliotheken bereitstellt. Die Anwendung verwendet SQLite als Datenbank, SQLAlchemy als ORM und bietet optionale Hintergrund-Worker für Synchronisations-, Matching- und Scan-Aufgaben.

## Features

- Modularer Aufbau mit Core-Clients und Routern
- OAuth-basierter Spotify-Client mit Rate-Limiting und Retry-Logik
- Plex-Client zur Abfrage der Musikbibliothek
- Asynchroner Soulseek-Client (slskd) mit Rate-Limiting
- Persistente Soulseek-Downloads mit Fortschritts- und Statusverfolgung
- Matching-Engine für Spotify→Plex sowie Spotify→Soulseek
- SQLite-Datenbank mit automatischer Initialisierung
- Hintergrund-Worker für Sync-, Matching-, Scan- und Spotify-Playlist-Prozesse
- Pytest-Test-Suite mit gemockten externen Diensten
- Docker- und Docker-Compose-Konfiguration
- GitHub Actions Workflow für Build & Tests

## Beets CLI Integration

Harmony bindet die [Beets](https://beets.io/)-CLI über einen synchronen Client ein.
Der `BeetsClient` ruft intern Befehle wie `beet import`, `beet update`,
`beet ls`, `beet stats` und `beet version` auf, um die lokale Musikbibliothek zu
verwalten. Damit die Integration funktioniert, muss das Kommando `beet`
installiert und im `PATH` der Anwendung verfügbar sein.

## Neu in v1.3.0

- Spotify-Playlist-Sync-Worker aktualisiert persistierte Playlists alle 15 Minuten.
- `/spotify/playlists` liefert Track-Anzahl und Änderungszeitpunkt aus der Datenbank.

## Neu in v1.2.0

- Soulseek-Downloads werden automatisch in der Datenbank angelegt und mit Status-/Fortschritt gepflegt.
- Hintergrund-Sync-Worker pollt den Soulseek-Client und synchronisiert Downloadzustände.
- API-Endpunkte liefern Fortschrittsabfragen aus der Datenbank und erlauben Abbrüche einzelner Downloads.

## Neu in v1.1.0

- Konsistente JSON-Antworten für alle Plex- und Soulseek-Endpunkte inklusive klarer Fehlercodes.
- Verbesserte Fehler- und Logging-Strategie bei fehlgeschlagenen Datenbank- oder API-Zugriffen.
- Stabilere Hintergrund-Worker dank transaktionalem Session-Handling über `session_scope()`.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Konfiguration

Die Anwendung liest Konfigurationen aus Umgebungsvariablen:

| Variable               | Beschreibung                                  |
|------------------------|-----------------------------------------------|
| `SPOTIFY_CLIENT_ID`    | Spotify OAuth Client ID                        |
| `SPOTIFY_CLIENT_SECRET`| Spotify OAuth Client Secret                    |
| `SPOTIFY_REDIRECT_URI` | Spotify Redirect URI                           |
| `SPOTIFY_SCOPE`        | Optionaler Scope (Standard siehe Code)         |
| `PLEX_BASE_URL`        | Basis-URL des Plex Servers                     |
| `PLEX_TOKEN`           | Plex Auth Token                                |
| `PLEX_LIBRARY`         | Name der Musikbibliothek in Plex               |
| `SLSKD_URL`            | Basis-URL von slskd                            |
| `SLSKD_API_KEY`        | Optionaler API-Key für slskd                   |
| `DATABASE_URL`         | SQLAlchemy URL (Standard: `sqlite:///./harmony.db`) |
| `HARMONY_LOG_LEVEL`    | Logging-Level (`INFO`, `ERROR`, …)             |
| `HARMONY_DISABLE_WORKERS` | `1`, um Worker im Testbetrieb zu deaktivieren |

## Lokaler Start

```bash
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t harmony-backend .
docker compose up
```

## Endpunkte

Die wichtigsten API-Endpunkte sind:

- `GET /spotify/status`
- `GET /spotify/search/tracks?query=...`
- `GET /spotify/search/artists?query=...`
- `GET /spotify/search/albums?query=...`
- `GET /spotify/playlists`
- `GET /spotify/track/{track_id}`
- `GET /plex/status`
- `GET /plex/artists`
- `GET /plex/artist/{artist_id}/albums`
- `GET /plex/album/{album_id}/tracks`
- `GET /soulseek/status`
- `POST /soulseek/search`
- `POST /soulseek/download`
- `GET /soulseek/downloads`
- `DELETE /soulseek/download/{id}`
- `POST /matching/spotify-to-plex`
- `POST /matching/spotify-to-soulseek`
- `GET /settings`
- `POST /settings`

## Lizenz

MIT
