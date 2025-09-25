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
- **Automatische Metadaten-Anreicherung**: Nach jedem Download ergänzt Harmony Genre, Komponist, Produzent, ISRC und Copyright, bettet Cover in höchster verfügbarer Auflösung ein und stellt die Tags per API bereit.
- **Automatic Lyrics**: Für jeden neuen Download erzeugt Harmony automatisch eine synchronisierte LRC-Datei mit passenden Songtexten. Die Lyrics stammen vorrangig aus der Spotify-API; falls dort keine Texte verfügbar sind, greift Harmony auf externe Provider wie Musixmatch oder lyrics.ovh zurück.
- **Matching-Engine** zur Ermittlung der besten Kandidaten zwischen Spotify ↔ Plex/Soulseek inklusive Persistierung.
- **SQLite-Datenbank** mit SQLAlchemy-Modellen für Playlists, Downloads, Matches und Settings.
- **Hintergrund-Worker** für Soulseek-Synchronisation, Matching-Queue, Plex-Scans und Spotify-Playlist-Sync.
- **Docker & GitHub Actions** für reproduzierbare Builds, Tests und Continuous Integration.

## Smart Search

Die globale Suche (`POST /api/search`) kombiniert Spotify-, Plex- und Soulseek-Ergebnisse in einer normalisierten Trefferliste. Optional lassen sich drei Filter setzen:

- `genre`: Begrenzt die Ergebnisse auf ein bestimmtes Genre (z. B. `rock`).
- `year`: Filtert nach Veröffentlichungsjahr (`int`).
- `quality`: Erwartete Audioqualität, etwa `FLAC` oder `320kbps`. Streaming-Resultate (Spotify) werden bei aktivem Qualitätsfilter automatisch ausgeschlossen.

Die Antwort enthält für jeden Treffer konsistente Felder (`id`, `source`, `type`, `artist`, `album`, `title`, `year`, `quality`) und führt alle Quellen in einer Liste zusammen. Fehler einzelner Dienste werden im Feld `errors` gesammelt und blockieren den Gesamtaufruf nicht.

## Complete Discographies

Harmony kann komplette Künstler-Diskografien automatisiert herunterladen. Für einen Spotify-Artist werden alle Alben samt Tracks
ermittelt, mit der Plex-Bibliothek abgeglichen und fehlende Titel über Soulseek nachgeladen. Nach dem Download übernimmt Beets die
Kategorisierung.

Beispiel-API-Aufruf:

```bash
curl -X POST \
  http://localhost:8000/soulseek/discography/download \
  -H 'Content-Type: application/json' \
  -d '{"artist_id": "123"}'
```

Der Status der Discography-Jobs wird in der Datenbank protokolliert und kann über die Soulseek- und Matching-Endpunkte
nachverfolgt werden.

## Automatic Lyrics

Nach erfolgreich abgeschlossenen Downloads erstellt Harmony automatisch eine `.lrc`-Datei mit synchronisierten Lyrics und legt sie im gleichen Verzeichnis wie die Audiodatei ab. Die Lyrics werden zuerst über die Spotify-API (Felder `sync_lyrics` oder `lyrics`) geladen; fehlt dort ein Treffer, nutzt Harmony die Musixmatch-API oder den öffentlichen Dienst lyrics.ovh als Fallback. Der Fortschritt wird im Download-Datensatz gespeichert (`has_lyrics`, `lyrics_status`, `lyrics_path`).

Über den Endpoint `GET /soulseek/download/{id}/lyrics` lässt sich der Inhalt der generierten LRC-Datei abrufen; solange die Generierung noch läuft, liefert der Endpunkt eine `202`-Antwort mit dem Status `pending`. Mit `POST /soulseek/download/{id}/lyrics/refresh` kann jederzeit ein erneuter Abruf erzwungen werden, etwa wenn neue Lyrics verfügbar geworden sind.

Beispiel einer erzeugten `.lrc`-Datei:

```text
[ti:Example Track]
[ar:Example Artist]
[al:Example Album]
[00:00.00]Line one
[00:14.50]Line two
[00:29.00]Line three
```

## Rich Metadata

Der neue Metadata-Worker lauscht auf abgeschlossene Downloads und reichert jede Audiodatei mit zusätzlichen Tags an. Die Informationen stammen primär aus der Spotify-API (Track-, Album- und Künstlerdaten), fehlende Felder werden über Plex ergänzt. Harmony schreibt Genre, Komponist, Produzent, ISRC und Copyright direkt in die Mediendatei, persistiert die Werte in der `downloads`-Tabelle und stellt sie über `GET /soulseek/download/{id}/metadata` als JSON zur Verfügung. Über `POST /soulseek/download/{id}/metadata/refresh` kann jederzeit ein erneuter Enrichment-Lauf angestoßen werden – die API antwortet sofort mit `202`, während der Worker im Hintergrund Spotify- und Plex-Daten abgleicht und die Tags neu schreibt.

Beispielantwort:

```json
{
  "id": 42,
  "filename": "Artist - Track.flac",
  "genre": "House",
  "composer": "Composer A",
  "producer": "Producer B",
  "isrc": "ISRC123456789",
  "copyright": "2024 Example Records"
}
```

## High-Quality Artwork

Der Artwork-Worker lauscht auf abgeschlossene Downloads und lädt das zugehörige Albumcover in maximaler Spotify-Auflösung herunter. Die Originaldatei wird zentral im Verzeichnis `./artwork/` abgelegt; über die Umgebungsvariable `ARTWORK_DIR` (Fallback `HARMONY_ARTWORK_DIR`) lässt sich der Speicherort anpassen. Für jede Spotify-Album-ID wird das Bild nur einmal heruntergeladen und anschließend wiederverwendet. Beim Einbetten sorgt Mutagen für ID3/FLAC/MP4-Tags in Originalauflösung. Schlägt der Spotify-Abruf fehl, versucht Harmony das Artwork über Plex-Metadaten, Soulseek oder externe Dienste wie Last.fm oder MusicBrainz zu ermitteln. Der Download-Datensatz speichert neben Pfad (`artwork_path`) und Status (`has_artwork`) nun auch die zugehörigen Spotify-IDs (`spotify_track_id`, `spotify_album_id`).

Über den Endpoint `GET /soulseek/download/{id}/artwork` liefert die API das eingebettete Cover direkt als `image/jpeg` (inkl. korrektem MIME-Type). Ist noch kein Artwork verfügbar, antwortet der Server mit `404`. Mit `POST /soulseek/download/{id}/artwork/refresh` lässt sich jederzeit ein erneuter Abruf auslösen, etwa wenn bessere Quellen verfügbar geworden sind; das Cover wird dabei neu heruntergeladen, zwischengespeichert und erneut eingebettet.

## File Organization

Nach Abschluss eines Downloads verschiebt Harmony die Audiodatei automatisch in eine saubere, konsistente Verzeichnisstruktur unterhalb des Musik-Ordners (`MUSIC_DIR`, Standard: `./music`). Der endgültige Pfad folgt dem Muster `music/<Artist>/<Album>/<TrackNumber - Title>.<ext>`. Namen werden vor dem Verschieben normalisiert (Sonderzeichen, Slashes und doppelte Leerzeichen werden entfernt), sodass alle Betriebssysteme den Pfad zuverlässig verarbeiten.

- Ist kein Album in den Metadaten hinterlegt, versucht Harmony den Namen aus dem Dateinamen zu erraten. Gelingt dies nicht, landet der Track im Ordner `<Unknown Album>`.
- Fehlt die Tracknummer, wird die Datei nur anhand des Titels benannt.
- Existiert bereits eine Datei mit gleichem Namen, erhält der neue Track automatisch den Suffix `_1`, `_2`, …

Der normalisierte Zielpfad wird zusätzlich in der Datenbank (`downloads.organized_path`) sowie in der API (`GET /soulseek/downloads`) persistiert. Externe Tools können so jederzeit nachvollziehen, wohin eine Datei verschoben wurde.

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
npm run test    # Lokale Jest/Vitest-Tests (in CI deaktiviert)
npm run build   # TypeScript + Vite Build
```

> **Hinweis:** In der CI-Umgebung werden Frontend-Tests übersprungen, da dort kein Zugriff auf die npm-Registry besteht. Lokal
> können die Tests weiterhin über Jest oder Vitest ausgeführt werden.

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
Requests ausschließlich die Backend-Tests (`pytest`) unter Python 3.11 aus. Frontend-Tests werden aufgrund fehlenden npm-Regis
try-Zugriffs im CI bewusst ausgelassen.

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
