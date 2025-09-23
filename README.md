# Harmony Backend

Harmony ist ein FastAPI-Backend, das Spotify, Plex, Soulseek (slskd), Beets sowie eine eigene Matching-Engine und Hintergrund-Worker
zu einem gemeinsamen Musik-Hub kombiniert. Die Anwendung bündelt Bibliotheken, Downloads und Metadaten, synchronisiert sie zyklisch
und stellt einheitliche JSON-APIs für Automatisierungen und Frontend-Clients bereit.

## Features

- **Harmony Web UI (React + Vite)** mit Dashboard, Service-Tabs, Tabellen, Karten und Dark-/Light-Mode.
- **Vollständige Spotify-Integration** für Suche, Playlists, Audio-Features, Empfehlungen und Benutzerbibliotheken.
- **Async Plex-Client** mit Zugriff auf Bibliotheken, Sessions, PlayQueues, Live-TV und Echtzeit-Benachrichtigungen.
- **Soulseek-Anbindung** inklusive Download-/Upload-Verwaltung, Warteschlangen und Benutzerinformationen.
- **Beets CLI Bridge** zum Importieren, Aktualisieren, Verschieben und Abfragen der lokalen Musikbibliothek.
- **Matching-Engine** zur Ermittlung der besten Kandidaten zwischen Spotify ↔ Plex/Soulseek inklusive Persistierung.
- **SQLite-Datenbank** mit SQLAlchemy-Modellen für Playlists, Downloads, Matches und Settings.
- **Hintergrund-Worker** für Soulseek-Synchronisation, Matching-Queue, Plex-Scans und Spotify-Playlist-Sync.
- **Docker & GitHub Actions** für reproduzierbare Builds, Tests und Continuous Integration.

## Harmony Web UI

Die neue React-basierte Oberfläche befindet sich im Verzeichnis [`frontend/`](frontend/). Sie orientiert sich am Porttracker-Layout mit Sidebar, Header, Karten, Tabellen und Tabs. Das UI nutzt Tailwind CSS, shadcn/ui (Radix UI Komponenten) und React Query für Live-Daten aus den bestehenden APIs.

![Harmony Dashboard](docs/harmony-ui.svg)

### Voraussetzungen

- Node.js ≥ 20
- pnpm oder npm (Beispiele verwenden npm)

### Installation & Entwicklung

```bash
cd frontend
npm install
npm run dev
```

Die Dev-Instanz ist standardmäßig unter `http://localhost:5173` erreichbar. Das Backend kann über die Umgebungsvariable `VITE_API_BASE_URL` angebunden werden (z. B. `http://localhost:8000`).

### Tests & Builds

```bash
npm run test    # Jest + Testing Library
npm run build   # TypeScript + Vite Build
```

### Features der UI

- Dashboard mit Systeminformationen, Service-Status und aktiven Jobs.
- Detailseiten für Spotify, Plex, Soulseek und Beets inkl. Tabs für Übersicht und Einstellungen.
- Matching-Ansicht mit Fortschrittsanzeigen.
- Settings-Bereich mit Formularen für sämtliche Integrationen.
- Dark-/Light-Mode Switch (Radix Switch) und globale Toast-Benachrichtigungen.

Alle REST-Aufrufe nutzen die bestehenden Endpunkte (`/spotify`, `/plex`, `/soulseek`, `/matching`, `/settings`, `/beets`) und werden alle 30 Sekunden automatisch aktualisiert.

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

### Beets-Integration

Die Harmony-Instanz nutzt die [`beet` CLI](https://beets.io/) für alle Operationen rund um die lokale Musikbibliothek. Stelle
 sicher, dass `beet` auf dem Host oder im Container installiert und über den `PATH` erreichbar ist, bevor du die Beets-Endpunk
 te aufrufst.

Beispiele für typische Aufrufe:

```bash
# Neuen Ordner importieren
curl -X POST http://localhost:8000/beets/import \
  -H 'Content-Type: application/json' \
  -d '{"path": "/music/new", "quiet": true, "autotag": true}'

# Bibliothek aktualisieren (optional mit Pfad)
http POST http://localhost:8000/beets/update path=/music/library

# Treffer suchen und formatiert ausgeben
curl -X POST http://localhost:8000/beets/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "artist:Radiohead", "format": "$artist - $album - $title"}'

# Einträge löschen (force löscht ohne Rückfrage)
http DELETE http://localhost:8000/beets/remove query=='artist:Radiohead' force:=true
```

Weitere Endpunkte:

- `GET /beets/albums` – listet alle Alben.
- `GET /beets/tracks` – listet alle Titel.
- `GET /beets/stats` – liefert Beets-Statistiken.
- `GET /beets/fields` – zeigt verfügbare Metadatenfelder.
- `POST /beets/move` & `POST /beets/write` – verschiebt Dateien bzw. schreibt Tags.

## Tests & CI

```bash
pytest
```

Die Tests mocken externe Dienste und können lokal wie auch via GitHub Actions ausgeführt werden. Für deterministische
Runs sollten die Worker mit `HARMONY_DISABLE_WORKERS=1` deaktiviert werden.

## Lizenz

Das Projekt steht derzeit ohne explizite Lizenzdatei zur Verfügung. Ohne eine veröffentlichte Lizenz gelten sämtliche Rechte
als vorbehalten.
