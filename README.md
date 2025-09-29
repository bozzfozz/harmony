# Harmony Backend

Harmony ist ein FastAPI-Backend, das Spotify, Soulseek (slskd) sowie eine eigene Matching-Engine und Hintergrund-Worker zu einem gemeinsamen Musik-Hub kombiniert. Die Anwendung bündelt Bibliotheken, Downloads und Metadaten, synchronisiert sie zyklisch und stellt einheitliche JSON-APIs für Automatisierungen und Frontend-Clients bereit.

> **MVP-Hinweis:** Die früheren Plex- und Beets-Integrationen sind vorübergehend deaktiviert und der Quellcode wurde unter `archive/integrations/plex_beets/` abgelegt. Markierte Abschnitte in diesem Dokument beschreiben archivierte Funktionen.

## Features

- **Harmony Web UI (React + Vite)** mit Dashboard, Service-Tabs, Tabellen, Karten und Dark-/Light-Mode.
- **Vollständige Spotify-Integration** für Suche, Playlists, Audio-Features, Empfehlungen und Benutzerbibliotheken.
- **Spotify FREE-Modus** für parserbasierte Imports ohne OAuth inklusive Free-Ingest-Pipeline: Text- oder Datei-Eingaben sowie bis zu 100 Playlist-Links werden normalisiert, dedupliziert und als Soulseek-Downloads in Batches eingeplant.
- **Spotify PRO Backfill** reichert bestehende FREE-Ingest-Daten nach OAuth-Setup automatisch mit Spotify-IDs, ISRCs und Laufzeiten an und expandiert gemeldete Playlist-Links zu vollständigen Tracklisten.
- **Soulseek-Anbindung** inklusive Download-/Upload-Verwaltung, Warteschlangen und Benutzerinformationen.
- **Integrationen-Adapter** erzwingen ein gemeinsames `MusicProvider`-Interface für Spotify, Plex (Stub) und slskd. Aktivierung erfolgt zentral über `INTEGRATIONS_ENABLED`, Fehler werden vereinheitlicht gemeldet und ein Diagnose-Endpoint listet Health-Status pro Provider.
- **Automatische Metadaten-Anreicherung**: Nach jedem Download ergänzt Harmony Genre, Komponist, Produzent, ISRC und Copyright, bettet Cover in höchster verfügbarer Auflösung ein und stellt die Tags per API bereit.
- **Globale API-Key-Authentifizierung** schützt sämtliche Produktiv-Endpunkte (`X-API-Key` oder `Authorization: Bearer`). Keys werden über `HARMONY_API_KEYS`/`HARMONY_API_KEYS_FILE` verwaltet, Ausnahmen via `AUTH_ALLOWLIST`, CORS über `ALLOWED_ORIGINS` restriktiv konfiguriert.
- **Automatic Lyrics** *(Feature-Flag `ENABLE_LYRICS`, Default: deaktiviert)*: Für jeden neuen Download erzeugt Harmony automatisch eine synchronisierte LRC-Datei mit passenden Songtexten. Die Lyrics stammen vorrangig aus der Spotify-API; falls dort keine Texte verfügbar sind, greift Harmony auf externe Provider wie Musixmatch oder lyrics.ovh zurück.
- **Matching-Engine** zur Ermittlung der besten Kandidaten zwischen Spotify ↔ Soulseek inklusive Persistierung (Plex-Matching archiviert).
- **SQLite-Datenbank** mit SQLAlchemy-Modellen für Playlists, Downloads, Matches und Settings.
- **Hintergrund-Worker** für Soulseek-Synchronisation, Matching-Queue und Spotify-Playlist-Sync.
- **Docker & GitHub Actions** für reproduzierbare Builds, Tests und Continuous Integration.

### Matching-Engine

- Unicode- und Akzent-Normalisierung (Fallback ohne `unidecode`), inklusive Vereinheitlichung typografischer Anführungszeichen.
- Konservative Titel-Varianten (Klammern ↔ Dash, Entfernung von `explicit`/`clean`/`feat.` ohne Verlust von Remix-/Live-Hinweisen).
- Künstler-Alias-Mapping (z. B. `Beyoncé` ↔ `Beyonce`, `KoЯn` ↔ `Korn`) für stabilere Artist-Scores.
- Mehrstufige Kandidatensuche: direkte LIKE-Queries, normalisierte LIKE-Suche und begrenztes Fuzzy-Matching.
- Editions-bewusstes Album-Matching mit Bonus/Penalty für Deluxe/Anniversary/Remaster-Varianten sowie Trackanzahl-Abgleich.
- Album-Completion-Berechnung mit Klassifizierung (`complete`, `nearly`, `incomplete`) und Confidence-Score `0.0–1.0`.

## Spotify Modi

Harmony kennt zwei Betriebsarten: **PRO** nutzt die vollständige OAuth-/API-Integration, **FREE** erlaubt parserbasierte
Imports ohne Spotify-Credentials. Der Modus wird per `GET/POST /spotify/mode` verwaltet und in der Settings-Tabelle persistiert.
Im FREE-Modus stehen neben den Parser-Endpunkten (`/spotify/free/*`) auch die Free-Ingest-Schnittstellen zur Verfügung:

- `POST /spotify/import/free` akzeptiert bis zu 100 Playlist-Links (`open.spotify.com`) sowie umfangreiche Tracklisten aus dem Request-Body, normalisiert Artist/Titel/Album/Dauer und legt persistente `ingest_jobs`/`ingest_items` an.
- `POST /spotify/import/free/upload` nimmt `multipart/form-data` (CSV/TXT/JSON) entgegen, parst serverseitig in Tracks und ruft intern den Free-Ingest-Service auf.
- `GET /spotify/import/jobs/{job_id}` liefert den Job-Status inklusive Zählern (`registered`, `normalized`, `queued`, `failed`, `completed`) sowie Skip-Gründen.

Die Ingest-Pipeline teilt sich für FREE- und PRO-Quellen dieselben Datenstrukturen
(`ingest_jobs`, `ingest_items`) und Zustände (`registered` → `normalized` → `queued`
→ `completed`/`failed`). Responses enthalten konsistente `accepted`/`skipped`
Blöcke sowie ein optionales `error`-Feld für Partial-Success-Szenarien
(HTTP `207`). Globale Einstellungen wie `INGEST_BATCH_SIZE` (Chunking) und
`INGEST_MAX_PENDING_JOBS` (Backpressure) steuern das Verhalten beider Modi.

Die Web-Oberfläche bietet hierfür einen dedizierten Spotify-Screen mit Modus-Schalter, Importkarte und Job-Übersicht.

### PRO Backfill & Playlist-Expansion

Sobald gültige Spotify-Credentials für den PRO-Modus hinterlegt sind, lassen sich bestehende FREE-Ingest-Datensätze automatisch um Spotify-Metadaten ergänzen. Der Endpoint `POST /spotify/backfill/run` startet einen asynchronen Job (Payload z. B. `{ "max_items": 2000, "expand_playlists": true }`) und liefert sofort eine `202`-Antwort mit Job-ID. Der Fortschritt und aggregierte Kennzahlen (`processed`, `matched`, `cache_hits`, `expanded_playlists`, `expanded_tracks`) können über `GET /spotify/backfill/jobs/{id}` abgefragt werden.

Der Backfill vergleicht Künstler/Titel/Album sowie die vorhandene Dauer (±2 Sekunden) mit der Spotify-Suche, berücksichtigt vorhandene ISRCs und nutzt ein persistentes Cache-Table (`spotify_cache`), um wiederholte Anfragen zu vermeiden. Playlist-Links (`ingest_items.source_type='LINK'`) werden optional expandiert: Der Worker ruft die Spotify-Playlist ab, legt pro Track einen neuen `ingest_item` mit `source_type='PRO_PLAYLIST_EXPANSION'` an und markiert den ursprünglichen Link-Eintrag als abgeschlossen.

Das Verhalten lässt sich über zwei Umgebungsvariablen konfigurieren:

- `BACKFILL_MAX_ITEMS` (Default `2000`): Obergrenze je Job für zu prüfende Ingest-Tracks.
- `BACKFILL_CACHE_TTL_SEC` (Default `604800` = 7 Tage): Gültigkeitsdauer des `(artist,title,album)` → `spotify_track_id`-Caches.

## Smart Search

Die globale Suche (`POST /search`) aggregiert Spotify- und Soulseek-Ergebnisse in einer gemeinsamen Trefferliste mit einheitlichem Schema (`id`, `source`, `type`, `title`, `artists`, `album`, `year`, `duration_ms`, `bitrate`, `format`, `score`). Serverseitige Filter greifen nach der Aggregation und unterstützen folgende Kriterien:

- `types`: Liste der gewünschten Entitätstypen (`track`, `album`, `artist`).
- `genres`: Mehrere Genres, case-insensitiv verglichen.
- `year_range`: Bereich `[min, max]` für Veröffentlichungsjahre.
- `duration_ms`: Bereich `[min, max]` für die Laufzeit in Millisekunden.
- `explicit`: `true`/`false` zur Einschränkung auf Spotify-Tracks mit oder ohne Explicit-Flag.
- `min_bitrate`: Mindestbitrate in kbps (wirkt auf Soulseek-Dateien).
- `preferred_formats`: Liste bevorzugter Audioformate, die das Ranking beeinflusst.
- `username`: Soulseek-spezifischer Filter auf einen bestimmten Benutzer.

Die Ergebnisse lassen sich über `sort` nach `relevance`, `bitrate`, `year` oder `duration` (auf- oder absteigend) ordnen und per `pagination` (`page`, `size`, max. 100) seitenweise abrufen. Teilfehler einzelner Quellen werden als `errors` ausgewiesen, ohne den Gesamtabruf zu blockieren.

## Complete Discographies _(archiviert)_

Die Discography-Funktion benötigte Plex- und Beets-Integrationen und ist im MVP deaktiviert. Der historische Code liegt im Archiv (`archive/integrations/plex_beets/`).

## Artist Watchlist

Die Watchlist überwacht eingetragene Spotify-Künstler automatisch auf neue Releases. Ein periodischer Worker fragt die Spotify-API (Default alle 24 Stunden) nach frischen Alben und Singles ab, gleicht die enthaltenen Tracks mit der Download-Datenbank ab und stößt nur für fehlende Songs einen Soulseek-Download über den bestehenden `SyncWorker` an.

- `POST /watchlist` registriert einen Artist anhand der Spotify-ID. Beim Anlegen wird `last_checked` auf „jetzt“ gesetzt, sodass nur zukünftige Veröffentlichungen berücksichtigt werden.
- `GET /watchlist` liefert alle eingetragenen Artists inklusive Zeitstempel des letzten Checks.
- `DELETE /watchlist/{id}` entfernt einen Eintrag und beendet die Überwachung.

Mehrfachdownloads werden verhindert: Alle Tracks mit einem Download-Status ungleich `failed` oder `cancelled` werden übersprungen. Fehlerhafte Soulseek-Suchen werden protokolliert, blockieren den Worker aber nicht. Das Intervall kann über die Umgebungsvariable `WATCHLIST_INTERVAL` (Sekunden) angepasst werden.

## Automatic Lyrics

Nach erfolgreich abgeschlossenen Downloads erstellt Harmony automatisch eine `.lrc`-Datei mit synchronisierten Lyrics und legt sie im gleichen Verzeichnis wie die Audiodatei ab. Die Lyrics werden zuerst über die Spotify-API (Felder `sync_lyrics` oder `lyrics`) geladen; fehlt dort ein Treffer, nutzt Harmony die Musixmatch-API oder den öffentlichen Dienst lyrics.ovh als Fallback. Der Fortschritt wird im Download-Datensatz gespeichert (`has_lyrics`, `lyrics_status`, `lyrics_path`).

> **Feature-Flag:** Lyrics sind standardmäßig deaktiviert. Setze `ENABLE_LYRICS=true` (oder aktiviere das Setting in der Datenbank), damit Worker und Endpunkte starten; andernfalls antworten `/soulseek/download/{id}/lyrics*` konsistent mit `503 FEATURE_DISABLED`.

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

Der Metadata-Worker lauscht auf abgeschlossene Downloads und reichert jede Audiodatei mit zusätzlichen Tags an. Die Informationen stammen vollständig aus der Spotify-API (Track-, Album- und Künstlerdaten); die frühere Plex-Anreicherung wurde archiviert. Harmony schreibt Genre, Komponist, Produzent, ISRC und Copyright direkt in die Mediendatei, persistiert die Werte in der `downloads`-Tabelle und stellt sie über `GET /soulseek/download/{id}/metadata` als JSON zur Verfügung. Über `POST /soulseek/download/{id}/metadata/refresh` lässt sich jederzeit ein erneuter Enrichment-Lauf anstoßen.

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

Der Artwork-Worker lauscht auf abgeschlossene Downloads und lädt das zugehörige Albumcover in Originalauflösung. Primärquelle ist die Spotify-API; das größte verfügbare Bild landet im lokalen Cache-Verzeichnis (`ARTWORK_DIR`, Default `./artwork`). Für jede Spotify-Album-ID bzw. Fallback-MBID wird exakt eine Datei (`<id>_original.<ext>`) vorgehalten und für nachfolgende Titel wiederverwendet. Vor dem Einbetten prüft der Worker vorhandene Cover: nur fehlende oder als „low-res“ eingestufte Embeds werden ersetzt (`ARTWORK_MIN_EDGE`, `ARTWORK_MIN_BYTES`). Optional lässt sich ein Fallback auf MusicBrainz + Cover Art Archive aktivieren (`ARTWORK_FALLBACK_ENABLED=true`, `ARTWORK_FALLBACK_PROVIDER=musicbrainz`). Dabei sind nur die Hosts `musicbrainz.org` und `coverartarchive.org` erlaubt; Timeouts und Download-Größen lassen sich getrennt konfigurieren (`ARTWORK_HTTP_TIMEOUT`, `ARTWORK_MAX_BYTES`, `ARTWORK_FALLBACK_TIMEOUT_SEC`, `ARTWORK_FALLBACK_MAX_BYTES`, `ARTWORK_WORKER_CONCURRENCY`). Nach erfolgreichem Einbetten aktualisiert Harmony den Download-Datensatz (Pfad `artwork_path`, Status `has_artwork`, Cache-Hits `artwork_status`) und speichert die zugehörigen Spotify-IDs (`spotify_track_id`, `spotify_album_id`). Der frühere Beets-Poststep ist archiviert und im MVP deaktiviert.

> **Feature-Flag:** Artwork ist standardmäßig deaktiviert. Setze `ENABLE_ARTWORK=true` (oder aktiviere das Setting in der Datenbank), damit Worker und Endpunkte laufen; solange der Flag `false` ist, liefern `/soulseek/download/{id}/artwork*` eine `503 FEATURE_DISABLED`-Antwort.

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

Die Dev-Instanz ist standardmäßig unter `http://localhost:5173` erreichbar. Das Backend kann über die Umgebungsvariablen `VITE_API_URL` (Host, z. B. `http://localhost:8000`) und optional `VITE_API_BASE_PATH` (Default: `/api/v1`) angebunden werden.

### API-Key-Authentifizierung im Frontend

Das Frontend setzt API-Keys automatisch auf jede Anfrage, sofern Authentifizierung aktiv ist. Die Konfiguration erfolgt über folgende Variablen:

```bash
# .env.local
VITE_REQUIRE_AUTH=true             # blockiert Netzaufrufe ohne Key (Default: true)
VITE_AUTH_HEADER_MODE=x-api-key    # oder "bearer" für Authorization-Header
VITE_API_KEY=dev-local-key         # optionaler Build-Zeit-Key (nur lokal verwenden)
```

Die Auflösung des API-Keys erfolgt priorisiert: `VITE_API_KEY` → `localStorage[HARMONY_API_KEY]` → Laufzeitkonfiguration (z. B. über `window.__HARMONY_RUNTIME_API_KEY__`). Bei aktivem `VITE_REQUIRE_AUTH=true` und fehlendem Schlüssel werden Requests vor dem Versand abgebrochen und liefern `{ ok: false, error: { code: "AUTH_REQUIRED", message: "API key missing" } }` zurück.

Für lokale Entwicklung stellt die Einstellungsseite ein Panel bereit, das den Key maskiert anzeigt, explizit offenlegt und das Speichern/Löschen im Browser ermöglicht. Das Panel beeinflusst ausschließlich den lokalen Storage und überschreibt keine Build-Zeit-Variablen.

### Tests & Builds

```bash
npm test          # Jest-Suite im jsdom-Environment
npm run typecheck # TypeScript Strict-Checks (`tsc --noEmit`)
npm run build     # TypeScript + Vite Build
```

> **Hinweis:** Die CI führt alle drei Befehle auf jedem Push/PR aus. Lokal hilft `npm ci`, eine saubere Umgebung analog zur
> Pipeline zu erstellen.

## Lokale Checks & CI-Gates

Die GitHub-Actions-Pipeline validiert Backend und Frontend parallel. Vor einem Commit empfiehlt sich derselbe Satz an Prüfungen:

```bash
ruff check .
black --check .
mypy app
pytest -q
python scripts/audit_wiring.py

cd frontend
npm ci
npm test
npm run typecheck
npm run build
```

## Datenbank-Migrationen

- `make db.upgrade` führt `alembic upgrade head` aus und wendet alle offenen Migrationen auf die konfigurierte Datenbank an.
- `make db.revision msg="..."` erzeugt auf Basis der SQLAlchemy-Models eine neue, automatisch generierte Revision.
- Der Docker-Entrypoint führt Migrationen beim Start automatisch aus; setze `FEATURE_RUN_MIGRATIONS=off`, um dies temporär zu deaktivieren (z. B. für lokale Debug-Sessions).

### Code-Qualität lokal (optional offline)

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
# Tools vollständig:
make all
# Offline-Fallback (nur Pflichtgates laufen):
CI_OFFLINE=true make all
```

### Features der UI

- Dashboard mit Systeminformationen, Service-Status und aktiven Jobs.
- Library-Seite bündelt Artists, Downloads und Watchlist mit konsistenter Tab-Navigation; nur der aktive Tab wird lazy geladen und führt Polling aus.
- Detailseiten für Spotify und Soulseek inkl. Tabs für Übersicht und Einstellungen (Plex/Beets-Ansichten archiviert).
- Matching-Ansicht mit Fortschrittsanzeigen.
- Settings-Bereich mit Formularen für sämtliche Integrationen.
- Dark-/Light-Mode Switch (Radix Switch) und globale Toast-Benachrichtigungen.

Alle REST-Aufrufe nutzen die aktiven Endpunkte (`/spotify`, `/soulseek`, `/matching`, `/settings`). Archivierte Routen (`/plex`, `/beets`) werden nicht mehr ausgeliefert.

### Fehlgeschlagene Downloads verwalten

- Im Downloads-Tab zeigt eine Badge "Fehlgeschlagen: N" den aktuellen Bestand. Die Zahl wird nur für den aktiven Tab geladen; Invalidation erfolgt nach Aktionen oder beim erneuten Aktivieren.
- Ein Klick auf die Badge aktiviert automatisch den Statusfilter „failed“ und blendet fehlgeschlagene Einträge in der Liste ein.
- Zeilen mit Status `failed` bieten nun direkte Aktionen: **Neu starten** (POST `/downloads/{id}/retry`) und **Entfernen** (DELETE `/downloads/{id}`) aktualisieren Tabelle und Badge unmittelbar.
- Ein globaler Button **Alle fehlgeschlagenen erneut versuchen** triggert optional `/downloads/retry-failed`. Die Aktion wird nur angeboten, wenn der Endpoint erreichbar ist und fordert vor dem Start eine Bestätigung an.
- Während Requests sind Buttons deaktiviert; inaktive Tabs poll nicht im Hintergrund.

## Architekturüberblick

Harmony folgt einer klar getrennten Schichten-Architektur:

- **Core**: Enthält API-Clients (`spotify_client.py`, `soulseek_client.py`) und die Matching-Engine. Die früheren Plex-/Beets-Clients liegen im Archiv.
- **Routers**: FastAPI-Router kapseln die öffentlich erreichbaren Endpunkte (Spotify, Soulseek, Matching, Settings). Archivierte Router (`/plex`, `/beets`) bleiben im Repository erhalten, sind aber nicht eingebunden.
- **Workers**: Asynchrone Tasks synchronisieren Playlists, Soulseek-Downloads und Matching-Jobs. Ein zusätzlicher Retry-Scheduler prüft fällige Downloads und sorgt für persistente Neuversuche mit exponentiellem Backoff.
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
| `SLSKD_BASE_URL` | Basis-URL des Soulseek-Daemons (Legacy: `SLSKD_URL`) |
| `SLSKD_API_KEY` | API-Key für slskd (falls gesetzt) |
| `DATABASE_URL` | SQLAlchemy Verbindungsstring (Standard: `sqlite:///./harmony.db`) |
| `HARMONY_LOG_LEVEL` | Log-Level (`INFO`, `DEBUG`, …) |
| `HARMONY_DISABLE_WORKERS` | `1` deaktiviert alle Hintergrund-Worker (z. B. für Tests) |
| `API_BASE_PATH` | Basispräfix für alle API-Routen (Default: `/api/v1`) |
| `FEATURE_ENABLE_LEGACY_ROUTES` | Aktiviert zusätzliche Legacy-Pfade ohne Versionierung (`true`/`false`, Default: `false`) |
| `ENABLE_ARTWORK` | Aktiviert Artwork-Worker und -Endpoints (`true`/`false`, Default: `false`) |
| `ENABLE_LYRICS` | Aktiviert Lyrics-Worker und -Endpoints (`true`/`false`, Default: `false`) |
| `INTEGRATIONS_ENABLED` | Kommagetrennte Liste aktivierter Provider (`spotify`, `plex`, `slskd`; Default: `spotify`) |
| `SPOTIFY_TIMEOUT_MS` | Timeout in Millisekunden für Spotify-Adapter (Default: `15000`) |
| `PLEX_TIMEOUT_MS` | Timeout in Millisekunden für Plex-Adapter (Default: `15000`) |
| `SLSKD_TIMEOUT_MS` | Timeout in Millisekunden für slskd-Adapter (Default: `8000`) |
| `SLSKD_RETRY_MAX` | Maximale Anzahl an Neuversuchen für Suchanfragen (Default: `3`) |
| `SLSKD_RETRY_BACKOFF_BASE_MS` | Basiswert für exponentielles Backoff mit Jitter (Default: `250`) |
| `SLSKD_PREFERRED_FORMATS` | Kommagetrennte Liste bevorzugter Formate für das Ranking |
| `SLSKD_MAX_RESULTS` | Obergrenze der zurückgegebenen Kandidaten (Default: `50`) |
| `PROVIDER_MAX_CONCURRENCY` | Maximale parallele Provider-Aufrufe (Default: `4`) |
| `RETRY_MAX_ATTEMPTS` | Maximale Anzahl an Download-Versuchen (Default: `10`) |
| `RETRY_BASE_SECONDS` | Basisverzögerung für exponentielles Backoff in Sekunden (Default: `60`) |
| `RETRY_JITTER_PCT` | Zufälliges Jitter (± Prozent) zur Vermeidung eines Thundering Herd (Default: `0.2`) |
| `RETRY_SCAN_INTERVAL_SEC` | Intervall des Retry-Schedulers in Sekunden (Default: `60`) |
| `RETRY_SCAN_BATCH_LIMIT` | Maximale Anzahl neu eingeplanter Downloads pro Scheduler-Lauf (Default: `100`) |
| `FEATURE_MATCHING_EDITION_AWARE` | Aktiviert editionsbewusstes Album-Matching (`true`/`false`, Default: `true`) |
| `MATCH_FUZZY_MAX_CANDIDATES` | Obergrenze der Kandidaten je Matching-Stufe (Default: `50`) |
| `MATCH_MIN_ARTIST_SIM` | Mindest-Artist-Similarität bevor eine Penalty greift (Default: `0.6`) |
| `MATCH_COMPLETE_THRESHOLD` | Anteil (`0.0–1.0`), ab dem ein Album als „complete“ gilt (Default: `0.9`) |
| `MATCH_NEARLY_THRESHOLD` | Anteil (`0.0–1.0`), ab dem ein Album als „nearly complete“ gilt (Default: `0.8`) |

> **Hinweis:** Spotify- und slskd-Zugangsdaten können über den `/settings`-Endpoint gepflegt und in der Datenbank persistiert werden. Beim Laden der Anwendung haben Werte aus der Datenbank Vorrang vor Umgebungsvariablen; letztere dienen weiterhin als Fallback.

## API-Endpoints

Eine vollständige Referenz der FastAPI-Routen befindet sich in [`docs/api.md`](docs/api.md). Die wichtigsten Gruppen im Überblick:

- **Spotify** (`/spotify`): Status, Suche, Track-Details, Audio-Features, Benutzerbibliothek, Playlists, Empfehlungen.
- **Spotify FREE** (`/spotify/free`): Parser- und Enqueue-Endpunkte für importierte Titel ohne OAuth-Integration.
- **Soulseek** (`/soulseek`): Status, Suche, Downloads/Uploads, Warteschlangen, Benutzerverzeichnisse und -infos. Enthält `/soulseek/downloads/{id}/requeue` für manuelle Neuversuche und liefert Retry-Metadaten (`state`, `retry_count`, `next_retry_at`, `last_error`).
- **Matching** (`/matching`): Spotify↔Soulseek-Matching sowie Album-Matching (Legacy-Plex-Routen liefern `404`).
- **Settings** (`/settings`): Key-Value Einstellungen inkl. History.
- **Integrationen** (`/integrations`): Diagnose-Endpunkt mit aktivierten Providern und Health-Status.

Archivierte Integrationen (Plex, Beets) befinden sich im Verzeichnis [`archive/integrations/plex_beets/`](archive/integrations/plex_beets/) und werden im aktiven Build nicht geladen.

## Contributing

Für neue Arbeiten bitte die [Task-Vorlage](docs/task-template.md) nutzen und im PR referenzieren.

## Tests & CI

```bash
pytest
```

Die Tests mocken externe Dienste und können lokal wie auch via GitHub Actions ausgeführt werden. Für deterministische
Runs sollten die Worker mit `HARMONY_DISABLE_WORKERS=1` deaktiviert werden.

## Lizenz

Das Projekt steht derzeit ohne explizite Lizenzdatei zur Verfügung. Ohne eine veröffentlichte Lizenz gelten sämtliche Rechte
als vorbehalten.
