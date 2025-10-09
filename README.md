# Harmony Backend

Harmony ist ein FastAPI-Backend, das Spotify, Soulseek (slskd) sowie eine eigene Matching-Engine und Hintergrund-Worker zu einem gemeinsamen Musik-Hub kombiniert. Die Anwendung bündelt Bibliotheken, Downloads und Metadaten, synchronisiert sie zyklisch und stellt einheitliche JSON-APIs für Automatisierungen und Frontend-Clients bereit.

> **MVP-Hinweis:** Die frühere Plex-Integration ist vorübergehend deaktiviert und der Legacy-Code wurde aus dem Repository entfernt. Markierte Abschnitte in diesem Dokument beschreiben archivierte Funktionen.

## Architecture

Harmony setzt auf ein geschichtetes Kernsystem (Router → Services → Domain → Integrationen) mit einem zentralen Orchestrator für Hintergrundjobs. Verantwortlichkeiten, Flows, Fehler- und Logging-Verträge sowie Erweiterungspunkte sind in der [Architecture Overview](docs/architecture/overview.md) festgehalten und gelten als verbindliche Referenz für jede Änderung. Ergänzende Diagramme, Contracts und ADRs befinden sich im Ordner `docs/architecture/`.

## Projektstatus

Einen aktuellen Überblick über erledigte, laufende und offene Arbeiten findest du im [Projektstatus-Dashboard](docs/project_status.md).

## Features

- **Harmony Web UI (React + Vite)** mit Dashboard, Service-Tabs, Tabellen, Karten und Dark-/Light-Mode.
- **Artist Watchlist & Detail UI** unter `/artists` mit Prioritäts-Management, Match-Kuration und Queue-Aktionen (siehe [docs/frontend/artists-ui.md](docs/frontend/artists-ui.md)).
- **Vollständige Spotify-Integration** für Suche, Playlists, Audio-Features, Empfehlungen und Benutzerbibliotheken.
- **Spotify FREE-Modus** für parserbasierte Imports ohne OAuth inklusive Free-Ingest-Pipeline: Text- oder Datei-Eingaben sowie bis zu 100 Playlist-Links werden normalisiert, dedupliziert und als Soulseek-Downloads in Batches eingeplant.
- **Free Playlist Links UI** unter `/free/links` ermöglicht das direkte Erfassen, Validieren und Speichern einzelner oder mehrerer Spotify-Playlist-Links inklusive Erfolgs- und Skip-Status.
- **Spotify PRO Backfill** reichert bestehende FREE-Ingest-Daten nach OAuth-Setup automatisch mit Spotify-IDs, ISRCs und Laufzeiten an und expandiert gemeldete Playlist-Links zu vollständigen Tracklisten.
- **Soulseek-Anbindung** inklusive Download-/Upload-Verwaltung, Warteschlangen und Benutzerinformationen.
- **Integrations-Gateway** kapselt Spotify/slskd-Aufrufe hinter einem gemeinsamen `TrackProvider`-Contract. Retries, Timeout/Jitter, strukturiertes Logging (`api.dependency`) und Health-Checks laufen zentral; aktivierte Provider werden über `INTEGRATIONS_ENABLED` registriert.
- **Automatische Metadaten-Anreicherung**: Nach jedem Download ergänzt Harmony Genre, Komponist, Produzent, ISRC und Copyright, bettet Cover in höchster verfügbarer Auflösung ein und stellt die Tags per API bereit.
- **Globale API-Key-Authentifizierung** schützt sämtliche Produktiv-Endpunkte (`X-API-Key` oder `Authorization: Bearer`). Keys werden über `HARMONY_API_KEYS`/`HARMONY_API_KEYS_FILE` verwaltet, Ausnahmen via `AUTH_ALLOWLIST`, CORS über `ALLOWED_ORIGINS` restriktiv konfiguriert.
- **Automatic Lyrics** *(Feature-Flag `ENABLE_LYRICS`, Default: deaktiviert)*: Für jeden neuen Download erzeugt Harmony automatisch eine synchronisierte LRC-Datei mit passenden Songtexten. Die Lyrics stammen vorrangig aus der Spotify-API; falls dort keine Texte verfügbar sind, greift Harmony auf externe Provider wie Musixmatch oder lyrics.ovh zurück.
- **Matching-Engine** zur Ermittlung der besten Kandidaten zwischen Spotify ↔ Soulseek inklusive Persistierung (Plex-Matching archiviert).
- **PostgreSQL-Datenbank** mit SQLAlchemy-Modellen für Playlists, Downloads, Matches und Settings.
- **Hintergrund-Worker** für Soulseek-Synchronisation, Matching-Queue und Spotify-Playlist-Sync.
- **Docker & GitHub Actions** für reproduzierbare Builds, Tests und Continuous Integration.

## Unified Docker Image

Harmony wird als einziges Container-Image ausgeliefert, das Backend und vorgerendertes Frontend gemeinsam betreibt. Die Runtime hört standardmäßig auf Port `8080` – `GET /` liefert die SPA-Shell, `GET /api/health/ready` meldet `{ "status": "ok" }`, sobald Datenbank und Integrationen bereitstehen.

### Quickstart (`docker run`)

```bash
docker run -d \
  --name harmony \
  -p 8080:8080 \
  -e HARMONY_API_KEYS=change-me \
  -e POSTGRES_HOST=postgres \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=harmony \
  -e POSTGRES_USER=harmony \
  -e POSTGRES_PASSWORD=harmony \
  -e DATABASE_SSLMODE=disable \
  -e DATABASE_URL=postgresql+psycopg://harmony:harmony@postgres:5432/harmony?sslmode=disable \
  -e PUBLIC_BACKEND_URL=http://localhost:8080 \
  -e ALLOWED_ORIGINS=http://localhost:8080 \
  -v $(pwd)/data:/data \
  ghcr.io/bozzfozz/harmony:latest
```

> ℹ️ Stelle sicher, dass ein PostgreSQL-Server (z. B. `postgres:16`) im selben
> Docker-Netzwerk unter dem Hostnamen `postgres` erreichbar ist. Für lokale
> Tests genügt `docker network create harmony && docker run --rm -d --network
> harmony --name postgres -e POSTGRES_DB=harmony -e POSTGRES_USER=harmony -e
> POSTGRES_PASSWORD=harmony postgres:16`. Der Container liest `DATABASE_URL`
> oder baut bei Bedarf automatisch eine Verbindung aus den `POSTGRES_*`-
> Variablen.

### PostgreSQL Setup & Migrationen

1. **Service-Container starten:**

   ```bash
   docker compose up -d postgres
   # oder manuell:
   docker run --rm -d \
     --name harmony-postgres \
     -e POSTGRES_DB=harmony \
     -e POSTGRES_USER=harmony \
     -e POSTGRES_PASSWORD=harmony \
     -p 5432:5432 \
     postgres:16
   ```

2. **Verbindungs-DSN prüfen:** Die Anwendung akzeptiert ausschließlich
   PostgreSQL-Verbindungszeichenketten (`postgresql+psycopg://` oder
   `postgresql+asyncpg://`). Ein vollständiges Beispiel inklusive SSL-Mode
   lautet `postgresql+psycopg://harmony:harmony@localhost:5432/harmony?sslmode=disable`.

3. **Migrationen ausführen:**

   ```bash
   # Lokal (Poetry oder virtualenv aktivieren)
   alembic upgrade head

   # Oder im laufenden Container
   docker compose exec harmony alembic upgrade head
   ```

   Der Container ruft beim Start automatisch `./scripts/db/migrate.sh` auf. Das
   Skript wartet optional (via `pg_isready`) auf PostgreSQL und führt anschließend
   `alembic upgrade head` aus. Der Vorgang ist idempotent und überspringt bereits
   vorhandene Tabellen oder Indizes. Für historisch manuell angelegte Schemas
   genügt ein einmaliger `alembic upgrade head`; alternativ kann ein bekannter
   Stand mit `alembic stamp head` markiert werden.

### `compose.yaml`

Im Repository liegt ein vorkonfiguriertes [`compose.yaml`](compose.yaml), das genau einen Service (`harmony`) startet. Die Healthcheck-Definition prüft `GET http://localhost:8080/api/health/ready`; `docker compose up -d` genügt für lokale Tests.

```bash
docker compose up -d
open http://localhost:8080
```

Für Entwicklungszyklen steht [`compose.override.yaml`](compose.override.yaml) bereit. Das Override aktiviert den lokalen Build (`build: .`), setzt `uvicorn --reload` und bindet `./app` in den Container ein.

### Relevante Umgebungsvariablen

| Variable                 | Beschreibung                                                                 | Default (`compose.yaml`) |
| ------------------------ | ---------------------------------------------------------------------------- | ------------------------ |
| `DATABASE_URL`           | Persistente PostgreSQL-Datenbank (z. B. `postgresql+psycopg://user:pass@host:5432/db?sslmode=prefer`). | `postgresql+psycopg://harmony:harmony@postgres:5432/harmony?sslmode=disable` |
| `POSTGRES_HOST`          | Hostname des PostgreSQL-Servers (fällt auf `postgres`).                        | `postgres`                 |
| `POSTGRES_PORT`          | TCP-Port für PostgreSQL.                                                       | `5432`                    |
| `POSTGRES_DB`            | Datenbankname für Harmony.                                                     | `harmony`                 |
| `POSTGRES_USER`          | Benutzername für die Datenbankverbindung.                                      | `harmony`                 |
| `POSTGRES_PASSWORD`      | Passwort für die Datenbankverbindung.                                          | `harmony`                 |
| `DATABASE_SSLMODE`       | Optionaler `sslmode`-Parameter für PostgreSQL (`disable`, `prefer`, `require`, …). | `disable`                 |
| `HARMONY_API_KEYS`       | Kommagetrennte API-Schlüssel für Auth (`X-API-Key`).                            | `change-me`               |
| `ALLOWED_ORIGINS`        | CORS-Origin-Liste für Browser-Clients.                                         | `http://localhost:8080`   |
| `PUBLIC_BACKEND_URL`     | Basis-URL, die das Frontend zur API-Kommunikation verwendet.                   | `http://localhost:8080`   |
| `PUBLIC_SENTRY_DSN`      | Optionaler Sentry-DSN für das Frontend.                                        | _(leer)_                  |
| `PUBLIC_FEATURE_FLAGS`   | Optionales JSON für Feature-Flags (z. B. `{ "beta": true }`).                 | `{}`                      |
| `FEATURE_RUN_MIGRATIONS` | Steuert, ob der Container beim Start Alembic-Migrationen ausführt.             | `on`                      |
| `WAIT_FOR_POSTGRES`      | Deaktiviert bei Bedarf das Warten auf PostgreSQL vor den Migrationen.          | `on`                      |
| `POSTGRES_WAIT_ATTEMPTS` | Anzahl der `pg_isready`-Versuche vor dem Abbruch.                              | `60`                      |
| `POSTGRES_WAIT_INTERVAL` | Wartezeit (Sekunden) zwischen den Versuchen.                                   | `1`                       |

Weitere Konfigurationsvariablen findest du in [`app/config.py`](app/config.py) und der Tabelle in [`.env.example`](.env.example).

### Migration vom Dual-Image-Setup

- Entferne verwaiste Services (`backend`, `frontend`) aus eigenen Compose-/Kubernetes-Manifests und ersetze sie durch den einzigen Service `harmony`.
- Aktualisiere Port-Mappings auf `8080` und passe Upstream-Proxys entsprechend an.
- Health-Checks wechseln von `GET /ready` oder `/health` auf `GET /api/health/ready`.
- Die GitHub-Registry publiziert nur noch `ghcr.io/bozzfozz/harmony:<tag>` (`sha-<short>`, `v<semver>`, `latest`).

### Integrations-Gateway

- **Contracts & DTOs:** Spotify- und slskd-Adapter liefern `ProviderTrack`-, `ProviderAlbum`- und `ProviderArtist`-Modelle mit optionalen Kandidaten (`TrackCandidate`). Normalizer (`app/integrations/normalizers.py`) sorgen für defensive Konvertierung.
- **ProviderGateway:** Kapselt Timeout, Retry (exponentiell mit symmetrischem Jitter), strukturierte Logs (`api.dependency`) und ein zentrales Fehler-Mapping. Die maximale Parallelität wird über `PROVIDER_MAX_CONCURRENCY` begrenzt.
- **Registry:** `INTEGRATIONS_ENABLED` steuert, welche Provider instanziiert werden. Pro Provider greift eine eigene Retry-Policy auf Basis der ENV-Defaults (`SPOTIFY_TIMEOUT_MS`, `SLSKD_TIMEOUT_MS`, `SLSKD_RETRY_*`).
- **Health-Monitor:** `ProviderHealthMonitor` führt optionale `check_health()`-Probes aus und emittiert `integration.health`-Logs. Der Diagnoseroute `/integrations` liefert den aggregierten Status (`overall=ok|degraded|down`).

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
- `POST /spotify/free/links` erlaubt die direkte Eingabe einzelner oder mehrerer Playlist-Links/URIs, extrahiert die Playlist-ID, dedupliziert bereits laufende Jobs und stößt denselben Free-Ingest-Flow an (Response mit `accepted`/`skipped`).
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

Die Discography-Funktion benötigte zusätzliche Bibliotheksintegrationen (u. a. Plex) und ist im MVP deaktiviert. Der zugehörige Legacy-Code wurde aus dem Repository entfernt.

## Artists API

Unter `/api/v1/artists` steht eine schlanke REST-API bereit, die die gespeicherten Künstlerdaten aus der neuen Persistenzschicht exponiert. Die Endpunkte liefern ausschließlich die normalisierten DTOs (`ArtistOut`, `ReleaseOut`) und folgen dem konsistenten Fehler-Contract (`VALIDATION_ERROR`, `NOT_FOUND`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`).

### Endpunkte

- `GET /artists/{artist_key}` gibt das Künstlerprofil inklusive aller bekannten Releases zurück. `artist_key` entspricht der normalisierten Form `source:source_id` (z. B. `spotify:1Xyo4u8uXC1ZmMpatF05PJ`).
- `POST /artists/{artist_key}/enqueue-sync` stößt einen Orchestrator-Job an, um den Künstler bei den angebundenen Providern erneut zu synchronisieren. Mehrfaches Aufrufen ist idempotent und liefert `already_enqueued=true`, sobald der Job bereits in der Queue steht.
- `GET /artists/watchlist?limit=25&offset=0` liefert eine paginierte Ansicht der Watchlist-Einträge, sortiert nach Priorität und nächstem Cooldown (`limit` ∈ [1, 100], `offset` ≥ 0).
- `POST /artists/watchlist` legt einen Eintrag an bzw. aktualisiert ihn (`artist_key`, optional `priority`, `cooldown_until` im ISO-8601-Format).
- `DELETE /artists/watchlist/{artist_key}` entfernt einen Eintrag aus der Watchlist.

## Watchlist API

Die neue Watchlist-Domain unter `/api/v1/watchlist` kapselt CRUD-Operationen für die automatische Release-Überwachung und hält den Zustand vollständig im Service-Layer. Alle Endpunkte liefern strukturierte Events (`event=api.request`) inklusive Request-ID.

- `GET /watchlist` listet alle bekannten Einträge sortiert nach Priorität.
- `POST /watchlist` legt einen Eintrag mit `artist_key` und optionaler `priority` an (duplizierte Schlüssel resultieren in `409 CONFLICT`).
- `PATCH /watchlist/{artist_key}` aktualisiert die Priorität eines bestehenden Eintrags.
- `POST /watchlist/{artist_key}/pause` markiert einen Eintrag als pausiert und akzeptiert optionale Felder `reason` sowie `resume_at` (ISO-8601).
- `POST /watchlist/{artist_key}/resume` hebt eine Pause wieder auf.
- `DELETE /watchlist/{artist_key}` entfernt den Eintrag.

Beispiel:

```bash
curl -X POST -H "Content-Type: application/json" -H "X-API-Key: $HARMONY_API_KEY" \
  -d '{"artist_key": "spotify:alpha", "priority": 10}' \
  "https://harmony.local/api/v1/watchlist"

curl -X POST -H "Content-Type: application/json" -H "X-API-Key: $HARMONY_API_KEY" \
  -d '{"reason": "vacation", "resume_at": "2025-01-01T12:00:00Z"}' \
  "https://harmony.local/api/v1/watchlist/spotify:alpha/pause"
```

### Beispiele

```bash
curl -H "X-API-Key: $HARMONY_API_KEY" \
  "https://harmony.local/api/v1/artists/spotify:1Xyo4u8uXC1ZmMpatF05PJ"

curl -X POST -H "X-API-Key: $HARMONY_API_KEY" \
  "https://harmony.local/api/v1/artists/spotify:1Xyo4u8uXC1ZmMpatF05PJ/enqueue-sync"

curl -X POST -H "Content-Type: application/json" -H "X-API-Key: $HARMONY_API_KEY" \
  -d '{"artist_key": "spotify:alpha", "priority": 10, "cooldown_until": "2024-04-01T08:00:00Z"}' \
  "https://harmony.local/api/v1/artists/watchlist"
```

```json
{
  "artist_key": "spotify:1Xyo4u8uXC1ZmMpatF05PJ",
  "name": "The Weeknd",
  "source": "spotify",
  "releases": [
    {
      "title": "After Hours",
      "release_type": "album",
      "release_date": "2020-03-20"
    }
  ]
}
```

## Admin Artist Ops

Für Betriebs- und Supportaufgaben stehen zusätzliche Endpunkte unter `/admin/artists/*` bereit. Sie sind standardmäßig deaktiviert und werden nur eingebunden, wenn die Umgebungsvariable `FEATURE_ADMIN_API=true` gesetzt ist. Die Routen verwenden dieselbe API-Key-Authentifizierung wie die öffentlichen Schnittstellen und emittieren strukturierte Logs (`artist.admin.{dry_run,resync,audit,invalidate}`).

- `POST /admin/artists/{artist_key}/reconcile?dry_run=true|false` zeigt Delta-Vorschauen oder erzwingt eine sofortige Synchronisation. Bei `dry_run=true` werden keine Änderungen persistiert. Vor einem Write werden Locks (laufende Jobs) sowie das konfigurierbare Retry-Budget (`ARTIST_RETRY_BUDGET_MAX`, Default `6`) geprüft.
- `POST /admin/artists/{artist_key}/resync` legt einen `artist_sync`-Job mit erhöhter Priorität (`sync+10`) in die Queue und verweigert den Aufruf, falls bereits ein aktives Lease existiert oder das Retry-Budget ausgeschöpft ist.
- `GET /admin/artists/{artist_key}/audit?limit=100&cursor=<id>` liefert die jüngsten Audit-Ereignisse eines Künstlers paginiert (Cursor basiert auf der Audit-ID).
- `POST /admin/artists/{artist_key}/invalidate` verwirft zwischengespeicherte Responses (Artist- und Release-Routen) und stößt eine Cache-Neusynchronisation an.

Zusätzliche Sicherheitschecks informieren über veraltete Daten (konfigurierbar via `ARTIST_STALENESS_MAX_MIN`, Default `30` Minuten) und liefern Hinweise in der API-Antwort, ohne die Ausführung zu blockieren. Die Admin-Routen können jederzeit per Feature-Flag deaktiviert werden und haben keine Auswirkung auf die öffentliche `/api/v1`-API.

### Artist Sync (Backend)

Der Orchestrator-Job `artist_sync` ruft die Künstlerdaten über den `ProviderGateway` ab, normalisiert sie und führt sie in der
Artist-Persistenz zusammen. Ablauf im Überblick:

- Startet mit dem Payload `{"artist_key": ..., "force": bool}` und loggt den Lauf über `worker.job`.
- Für jeden angebundenen Provider wird ein `api.dependency`-Event mit Status (`ok`/`partial`/`failed`) protokolliert. Schlägt ein
  Provider vollständig fehl, wird der Job mit einem retry-fähigen Fehler beendet (Retry-Politik aus `RetryPolicyProvider`).
- Ermittelt über `app.services.artist_delta.determine_delta` nur die geänderten Releases und führt anschließend gezielt
  `ArtistDao.upsert_*`-Operationen aus; unveränderte Datensätze bleiben unangetastet, was Idempotenz und geringere Last sicherstellt.
- Entfernte Releases werden bei gesetztem `ARTIST_SYNC_PRUNE=true` weich deaktiviert (`inactive_at`, `inactive_reason='pruned'`).
  Mit `ARTIST_SYNC_HARD_DELETE=true` lassen sich entfernte Releases optional endgültig löschen – standardmäßig bleibt das Flag
  ausgeschaltet, sodass immer eine rücksetzbare Soft-Delete-Spur erhalten bleibt.
- Jeder Create/Update/Inactivate-Pfad schreibt einen Audit-Eintrag in die Tabelle `artist_audit` (Event, Entity, Before/After,
  `job_id`, `artist_key`). Alias-Änderungen werden als separate `event=updated`-Auditzeile festgehalten.
- Aktualisiert Watchlist-Einträge (`last_synced_at`, `cooldown_until`) und reduziert die Priorität optional über
  `ARTIST_SYNC_PRIORITY_DECAY`.
- Invalidiert HTTP-Caches (`ResponseCache.invalidate_prefix`) für `/artists/{artist_key}` (inkl. API-Basispfad), sodass API-Aufrufe
  sofort die neuen Daten erhalten.

Der Watchlist-Response enthält zusätzlich `priority`, `last_enqueued_at` und `cooldown_until`, sodass Clients kommende Läufe einplanen können. Fehlerantworten folgen dem Schema `{ "ok": false, "error": { "code": "…", "message": "…" } }`.

## Artist Workflow

Eine vollständige Beschreibung des Watchlist→Timer→Sync→API-Flows inklusive Fehlerszenarien, Idempotenz-Strategien und Cache-Invalidierung ist im Architektur-Dokument [docs/architecture/artist-workflow.md](docs/architecture/artist-workflow.md) festgehalten. Die End-to-End-Tests in `tests/e2e/test_artist_flow.py` prüfen den Happy Path, Cache-Bust nach Persistierung, Provider-Retries bis zur DLQ sowie doppelte Enqueue-Versuche.

### Relevante ENV-Flags

| Variable | Default | Beschreibung |
| --- | --- | --- |
| `WORKERS_ENABLED` | `true` | Globales Feature-Flag, das Scheduler, Dispatcher und Timer beim Start erzwingt bzw. deaktiviert. |
| `WATCHLIST_INTERVAL` | `86400` | Intervall in Sekunden, in dem der Watchlist-Worker Spotify/Soulseek prüft (leer = 24 h). |
| `WATCHLIST_TIMER_ENABLED` | `true` | Aktiviert den asynchronen Watchlist-Timer, der fällige Artists in die Queue legt. |
| `WATCHLIST_TIMER_INTERVAL_S` | `900` | Abstand zwischen Timer-Ticks in Sekunden (Default 15 Minuten). |
| `WATCHLIST_MAX_CONCURRENCY` | `3` | Maximale Anzahl paralleler Artists, die pro Tick verarbeitet werden. |
| `WATCHLIST_MAX_PER_TICK` | `20` | Obergrenze für neu enqueued Artists je Timer-Lauf. |
| `WATCHLIST_RETRY_MAX` | `3` | Versuche pro Tick, bevor der Eintrag auf den nächsten Lauf verschoben wird. |
| `WATCHLIST_RETRY_BUDGET_PER_ARTIST` | `6` | Gesamtbudget pro Artist; bei Erschöpfung wird ein Cooldown gesetzt. |
| `WATCHLIST_COOLDOWN_MINUTES` | `15` | Dauer des Cooldowns für blockierte Artists. |
| `WATCHLIST_BACKOFF_BASE_MS` | `250` | Basiswert für exponentielles Retry-Backoff (mit ±Jitter). |
| `WATCHLIST_JITTER_PCT` | `0.2` | Prozentualer Jitter für Backoff-Berechnungen (0.2 = 20 %). |
| `RETRY_POLICY_RELOAD_S` | `10` | TTL des Retry-Policy-Caches; steuert, wie oft ENV-Overrides neu eingelesen werden. |
| `RETRY_ARTIST_SYNC_MAX_ATTEMPTS` | `10` | Maximale Wiederholungen für `artist_sync`-Jobs bevor DLQ ausgelöst wird. |
| `RETRY_ARTIST_SYNC_BASE_SECONDS` | `60` | Grundintervall in Sekunden für den Backoff des `artist_sync`-Jobs. |
| `RETRY_ARTIST_SYNC_JITTER_PCT` | `0.2` | Jitter-Faktor für den Backoff des `artist_sync`-Jobs. |
| `RETRY_ARTIST_SYNC_TIMEOUT_SECONDS` | `–` | Optionales Timeout (Sekunden) für `artist_sync`-Retries; leer = kein Timeout. |

## Artist Watchlist

Die Watchlist überwacht eingetragene Spotify-Künstler automatisch auf neue Releases. Ein periodischer Worker fragt die Spotify-API (Default alle 24 Stunden) nach frischen Alben und Singles ab, gleicht die enthaltenen Tracks mit der Download-Datenbank ab und stößt nur für fehlende Songs einen Soulseek-Download über den bestehenden `SyncWorker` an.

- `POST /watchlist` registriert einen Artist anhand der Spotify-ID. Beim Anlegen wird `last_checked` auf „jetzt“ gesetzt, sodass nur zukünftige Veröffentlichungen berücksichtigt werden.
- `GET /watchlist` liefert alle eingetragenen Artists inklusive Zeitstempel des letzten Checks.
- `DELETE /watchlist/{id}` entfernt einen Eintrag und beendet die Überwachung.

Mehrfachdownloads werden verhindert: Alle Tracks mit einem Download-Status ungleich `failed` oder `cancelled` werden übersprungen. Fehlerhafte Soulseek-Suchen werden protokolliert, blockieren den Worker aber nicht. Das Intervall kann über die Umgebungsvariable `WATCHLIST_INTERVAL` (Sekunden) angepasst werden.

Nach ausgeschöpftem Retry-Budget setzt der Worker einen persistenten Cooldown pro Artist. Der Zeitstempel wird in `watchlist_artists.retry_block_until` gespeichert und überdauert Neustarts; während der Block aktiv ist, ignoriert der Worker den Eintrag und protokolliert das Ereignis als `event=watchlist.cooldown.skip`. Erfolgreiche Durchläufe löschen den Zeitstempel wieder (`event=watchlist.cooldown.clear`).

| Variable | Default | Beschreibung |
| --- | --- | --- |
| `WATCHLIST_DB_IO_MODE` | `thread` | Schaltet zwischen Thread-Offloading und einem nativen Async-DAO. |
| `WATCHLIST_MAX_CONCURRENCY` | `3` | Maximale Anzahl paralleler Künstler, die pro Tick verarbeitet werden. |
| `WATCHLIST_SPOTIFY_TIMEOUT_MS` | `8000` | Timeout für Spotify-Aufrufe (Alben & Tracks). |
| `WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS` | `12000` | Timeout für jede Soulseek-Suche. |
| `WATCHLIST_RETRY_MAX` | `3` | Maximale Versuche pro Tick und Künstler. |
| `WATCHLIST_BACKOFF_BASE_MS` | `250` | Basiswert für exponentiellen Backoff (mit ±20 % Jitter, gedeckelt bei 5 s). |
| `WATCHLIST_RETRY_BUDGET_PER_ARTIST` | `6` | Gesamtbudget pro Künstlerlauf – darüber greift der Cooldown. |
| `WATCHLIST_COOLDOWN_MINUTES` | `15` | Dauer, für die ein Künstler nach ausgeschöpftem Budget pausiert. |

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

Der Artwork-Worker lauscht auf abgeschlossene Downloads und lädt das zugehörige Albumcover in Originalauflösung. Primärquelle ist die Spotify-API; das größte verfügbare Bild landet im lokalen Cache-Verzeichnis (`ARTWORK_DIR`, Default `./artwork`). Für jede Spotify-Album-ID bzw. Fallback-MBID wird exakt eine Datei (`<id>_original.<ext>`) vorgehalten und für nachfolgende Titel wiederverwendet. Vor dem Einbetten prüft der Worker vorhandene Cover: nur fehlende oder als „low-res“ eingestufte Embeds werden ersetzt (`ARTWORK_MIN_EDGE`, `ARTWORK_MIN_BYTES`). Optional lässt sich ein Fallback auf MusicBrainz + Cover Art Archive aktivieren (`ARTWORK_FALLBACK_ENABLED=true`, `ARTWORK_FALLBACK_PROVIDER=musicbrainz`). Dabei sind nur die Hosts `musicbrainz.org` und `coverartarchive.org` erlaubt; Timeouts und Download-Größen lassen sich getrennt konfigurieren (`ARTWORK_HTTP_TIMEOUT`, `ARTWORK_MAX_BYTES`, `ARTWORK_FALLBACK_TIMEOUT_SEC`, `ARTWORK_FALLBACK_MAX_BYTES`, `ARTWORK_WORKER_CONCURRENCY`). Nach erfolgreichem Einbetten aktualisiert Harmony den Download-Datensatz (Pfad `artwork_path`, Status `has_artwork`, Cache-Hits `artwork_status`) und speichert die zugehörigen Spotify-IDs (`spotify_track_id`, `spotify_album_id`). Der frühere nachgelagerte Tagging-Poststep ist archiviert und im MVP deaktiviert.

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
npm ci --no-audit --no-fund
npm run dev
```

Die Dev-Instanz ist standardmäßig unter `http://localhost:5173` erreichbar. Das Backend kann über die Umgebungsvariablen `VITE_API_BASE_URL` (Host, z. B. `http://127.0.0.1:8000`) und optional `VITE_API_BASE_PATH` (Default: kein Präfix) angebunden werden.

### API-Key-Authentifizierung im Frontend

Das Frontend setzt API-Keys automatisch auf jede Anfrage, sofern Authentifizierung aktiv ist. Die Konfiguration erfolgt über folgende Variablen:

```bash
# .env.local
VITE_REQUIRE_AUTH=false            # blockiert Netzaufrufe ohne Key (Default: false)
VITE_AUTH_HEADER_MODE=x-api-key    # oder "bearer" für Authorization-Header
VITE_API_KEY=dev-local-key         # optionaler Build-Zeit-Key (nur lokal verwenden)
```

Die Auflösung des API-Keys erfolgt priorisiert: `VITE_API_KEY` → `localStorage[HARMONY_API_KEY]` → Laufzeitkonfiguration (z. B. über `window.__HARMONY_RUNTIME_API_KEY__`). Ist `VITE_REQUIRE_AUTH=false`, sendet der Client keine Auth-Header und lässt Requests ohne Key zu. Bei aktivem `VITE_REQUIRE_AUTH=true` und fehlendem Schlüssel werden Requests vor dem Versand abgebrochen und liefern `{ ok: false, error: { code: "AUTH_REQUIRED", message: "API key missing" } }` zurück.

Für lokale Entwicklung stellt die Einstellungsseite ein Panel bereit, das den Key maskiert anzeigt, explizit offenlegt und das Speichern/Löschen im Browser ermöglicht. Das Panel beeinflusst ausschließlich den lokalen Storage und überschreibt keine Build-Zeit-Variablen.

### Tests & Builds

```bash
npm run lint      # ESLint über das komplette Frontend
npm test          # Jest-Suite im jsdom-Environment
npm run typecheck # TypeScript Strict-Checks (`tsc --noEmit`)
npm run build     # TypeScript + Vite Build
```

> **Hinweis:** Die CI führt alle drei Befehle auf jedem Push/PR aus. Lokal hilft `npm ci`, eine saubere Umgebung analog zur
> Pipeline zu erstellen.

## Lokale Checks & CI-Gates

Die GitHub-Actions-Pipeline validiert Backend und Frontend parallel. Vor einem Commit empfiehlt sich derselbe Satz an Prüfungen:

```bash
ruff check . --select I --fix  # Import-Blöcke automatisch sortieren
ruff check .
black --check .
isort --check-only .
mypy app
pytest -q
python scripts/audit_wiring.py
pip-audit -r requirements.txt

cd frontend
npm ci --no-audit --no-fund
npm run lint
npm test -- --runInBand
npm run typecheck
npm run build
```

`ruff check . --select I --fix` sortiert sämtliche Imports gemäß den CI-Vorgaben (Stdlib → Third-Party → First-Party,
Gruppierung nach `known-first-party = ["app", "tests"]`). Die zusätzliche `isort --check-only .`-Stufe dient als Guard,
nutzt aber dieselbe Konfiguration. Für bewusst ungenutzte Importe (z. B. Test-Fixtures mit Seiteneffekten) bitte
`# noqa: F401` mit Begründung ergänzen.

`pip-audit -r requirements.txt` prüft alle direkten Abhängigkeiten auf bekannte CVEs und blockt Builds, sobald verwundbare
Pakete gefunden werden. Führe den Scan vor jedem Commit lokal aus oder verwende `make security`, das denselben Befehl bündelt.

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
- Detailseiten für Spotify und Soulseek inkl. Tabs für Übersicht und Einstellungen (Legacy-Plex-Ansichten archiviert).
- Matching-Ansicht mit Fortschrittsanzeigen.
- Settings-Bereich mit Formularen für sämtliche Integrationen.
- Dark-/Light-Mode Switch (Radix Switch) und globale Toast-Benachrichtigungen.

Alle REST-Aufrufe nutzen die aktiven Endpunkte (`/spotify`, `/soulseek`, `/matching`, `/settings`). Archivierte Routen (`/plex`) werden nicht mehr ausgeliefert.

### Fehlgeschlagene Downloads verwalten

- Im Downloads-Tab zeigt eine Badge "Fehlgeschlagen: N" den aktuellen Bestand. Die Zahl wird nur für den aktiven Tab geladen; Invalidation erfolgt nach Aktionen oder beim erneuten Aktivieren.
- Ein Klick auf die Badge aktiviert automatisch den Statusfilter „failed“ und blendet fehlgeschlagene Einträge in der Liste ein.
- Zeilen mit Status `failed` bieten nun direkte Aktionen: **Neu starten** (POST `/download/{id}/retry`) und **Entfernen** (DELETE `/download/{id}`) aktualisieren Tabelle und Badge unmittelbar.
- Während Requests sind Buttons deaktiviert; inaktive Tabs poll nicht im Hintergrund.

## Architekturüberblick

Harmony folgt einer klar getrennten Schichten-Architektur:

- **Core**: Enthält API-Clients (`spotify_client.py`, `soulseek_client.py`) und die Matching-Engine. Die frühere Plex-Client-Implementierung wurde entfernt.
- **Routers**: FastAPI-Router kapseln die öffentlich erreichbaren Endpunkte (Spotify, Soulseek, Matching, Settings). Archivierte Router (`/plex`) sind nicht eingebunden.
- **Workers**: Asynchrone Tasks synchronisieren Playlists, Soulseek-Downloads und Matching-Jobs. Ein zusätzlicher Retry-Scheduler prüft fällige Downloads und sorgt für persistente Neuversuche mit exponentiellem Backoff.
- **Datenbank-Layer**: `app/db.py`, SQLAlchemy-Modelle und -Schemas verwalten persistente Zustände.

Eine ausführliche Beschreibung der Komponenten findest du in [`docs/architecture.md`](docs/architecture.md).

### Router-Registry

- Alle produktiven Router werden zentral in `app/api/router_registry.py` registriert. Jedes Tupel enthält den Prefix (leer bedeutet „Router nutzt eigenen Prefix“), das Router-Objekt und optionale zusätzliche Tags.
- Neue Router fügst du hinzu, indem du sie in der Registry importierst, einen Eintrag in `get_domain_routers()` ergänzt und bei Bedarf `compose_prefix()` zum Zusammenbauen komplexerer Prefixe verwendest.
- Ergänze beim Hinzufügen eines Routers stets die Tests in `tests/routers/test_router_registry.py`, damit die Konfiguration stabil bleibt und OpenAPI unverändert bleibt.

## Setup-Anleitung

### Voraussetzungen

- Python 3.11
- Eine erreichbare PostgreSQL-Instanz (z. B. `postgres:16` via Docker)
- Optional: Docker und Docker Compose

Harmony unterstützt ausschließlich PostgreSQL als Datenbank-Backend; eingebettete oder file-basierte Engines funktionieren nicht mit den Migrationen und Tests.
Legacy-Dateistores aus frühen Experimenten gelten als reine Smoke-Hilfen und werden in produktiven oder CI-Szenarien nicht mehr berücksichtigt.

### Lokales Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# Passe `.env` gemäß den Tabellen im Abschnitt „Betrieb & Konfiguration" an.
uvicorn app.main:app --reload
```

Der Server liest die Laufzeitkonfiguration aus `.env`. Standardmäßig bindet die API an `127.0.0.1:8000` und lässt Requests ohne API-Key durch (`FEATURE_REQUIRE_AUTH=false`, `FEATURE_RATE_LIMITING=false`). Aktiviere Authentifizierung und Rate-Limits explizit, bevor du den Dienst über Loopback hinaus erreichbar machst. Verwende lokale Schlüssel und Secrets ausschließlich über `.env` oder einen Secret-Store – niemals eingecheckt in das Repository.

### Docker

Das veröffentlichte Container-Image `ghcr.io/bozzfozz/harmony` bündelt Backend und Frontend als Multi-Arch-Build (`linux/amd64`, `linux/arm64`). Die Tags werden von GitHub Actions vergeben:

- `ghcr.io/bozzfozz/harmony:sha-<short>` – jeder Commit auf `main`
- `ghcr.io/bozzfozz/harmony:v<semver>` – Release-Tags (`vX.Y.Z`)
- `ghcr.io/bozzfozz/harmony:latest` – nur der Kopf von `main`

Die wichtigsten Laufzeit-Variablen und Healthchecks sind im Abschnitt [„Unified Docker Image“](#unified-docker-image) dokumentiert. Für ein minimalistisches Deployment genügt:

```bash
docker run -d \
  --name harmony \
  -p 8080:8080 \
  -e HARMONY_API_KEYS=change-me \
  -e DATABASE_URL=postgresql+psycopg://harmony:harmony@postgres:5432/harmony \
  -v $(pwd)/data:/data \
  ghcr.io/bozzfozz/harmony:latest

> ℹ️ Die Runtime erwartet einen PostgreSQL-Server im selben Docker-Netzwerk.
```

Der Container lauscht auf `8080`, liefert `GET /` als HTML und meldet seine Bereitschaft über `GET /api/health/ready`. Persistente Daten (PostgreSQL-Datenbank, Caches, Artefakte) sollten auf ein Host-Volume unter `/data` gemountet werden. Ein Update erfolgt klassisch per `docker pull ghcr.io/bozzfozz/harmony:latest && docker compose up -d`.

### Docker Compose

Das Repository bringt ein [`compose.yaml`](compose.yaml) mit, das den Service `harmony` direkt aus der GitHub Container Registry startet. Optional lassen sich zusätzliche Einstellungen über `.env` oder ein Override-File steuern.

```yaml
services:
  harmony:
    image: ghcr.io/bozzfozz/harmony:latest
    depends_on:
      - postgres
    env_file:
      - ./.env
    environment:
      DATABASE_URL: postgresql+psycopg://harmony:harmony@postgres:5432/harmony
      HARMONY_API_KEYS: change-me
      ALLOWED_ORIGINS: http://localhost:8080
      PUBLIC_BACKEND_URL: http://localhost:8080
    ports:
      - "8080:8080"
    volumes:
      - harmony-data:/data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/api/health/ready"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: harmony
      POSTGRES_USER: harmony
      POSTGRES_PASSWORD: harmony
    ports:
      - "5432:5432"
    volumes:
      - harmony-pg-data:/var/lib/postgresql/data

volumes:
  harmony-data:
  harmony-pg-data:
```

[`compose.override.yaml`](compose.override.yaml) aktiviert bei Bedarf Hot-Reloading (`uvicorn --reload`) und einen lokalen Build. Zusätzliche Secrets können über `env_file` oder Compose-Profile eingebunden werden.

### GitHub Actions

Der Workflow [`.github/workflows/autopush.yml`](.github/workflows/autopush.yml) führt bei jedem Push auf `main` sowie bei Pull
Requests ausschließlich die Backend-Tests (`pytest`) unter Python 3.11 aus. Frontend-Tests werden aufgrund fehlenden npm-Regis
try-Zugriffs im CI bewusst ausgelassen.

## Betrieb & Konfiguration

### Backend-Umgebungsvariablen

Harmony löst Konfigurationswerte deterministisch in der Reihenfolge **Environment-Variablen → `.env` → Code-Default** auf. Eine lokale `.env` ist optional – ohne sie startet die Anwendung mit sicheren Dev-Defaults (z. B. `postgresql+psycopg://postgres:postgres@localhost:5432/harmony` als Datenbank-DSN). Für Produktionsumgebungen **müssen** die benötigten Variablen explizit per Environment gesetzt werden. Alle unterstützten Keys inklusive kommentierter Defaults sind in [`.env.example`](./.env.example) dokumentiert.

#### Kern & Sicherheit

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | string | `postgresql+psycopg://postgres:postgres@localhost:5432/harmony` | SQLAlchemy-Verbindungsstring zu einer PostgreSQL-Instanz. | 🔒 enthält ggf. Zugangsdaten |
| `ALEMBIC_DATABASE_URL` | string | _(leer)_ | Optionales Override ausschließlich für Alembic (`alembic upgrade`, `alembic revision`); muss auf PostgreSQL verweisen. | 🔒 enthält ggf. Zugangsdaten |
| `HARMONY_LOG_LEVEL` | string | `INFO` | Globale Log-Stufe (`DEBUG`, `INFO`, …). | — |
| `APP_ENV` | string | `dev` | Beschreibt die laufende Umgebung (`dev`, `staging`, `prod`). | — |
| `HOST` | string | `127.0.0.1` | Bind-Adresse für Uvicorn/Hypercorn – standardmäßig nur lokal erreichbar. | — |
| `PORT` | int | `8080` | TCP-Port der API-Instanz. | — |
| `HARMONY_DISABLE_WORKERS` | bool (`0/1`) | `false` | `true` deaktiviert alle Hintergrund-Worker (Tests/Demos). | — |
| `API_BASE_PATH` | string | `/api/v1` | Präfix für alle öffentlichen API-Routen inkl. OpenAPI & Docs. | — |
| `FEATURE_ENABLE_LEGACY_ROUTES` | bool | `false` | Aktiviert unversionierte Legacy-Routen – nur für Migrationsphasen. | — |
| `FEATURE_REQUIRE_AUTH` | bool | `false` | Erzwingt API-Key-Authentifizierung für alle nicht freigestellten Pfade. | — |
| `FEATURE_RATE_LIMITING` | bool | `false` | Aktiviert die globale Rate-Limit-Middleware (OPTIONS & Allowlist bleiben ausgenommen). | — |
| `HARMONY_API_KEYS` | csv | _(leer)_ | Kommagetrennte Liste gültiger API-Keys. | 🔒 niemals einchecken |
| `HARMONY_API_KEYS_FILE` | path | _(leer)_ | Datei mit einem API-Key pro Zeile (wird zusätzlich zu `HARMONY_API_KEYS` geladen). | 🔒 Dateirechte restriktiv |
| `AUTH_ALLOWLIST` | csv | automatisch `health`, `ready`, `docs`, `redoc`, `openapi.json` (mit Präfix) | Zusätzliche Pfade ohne Authentifizierung. | — |
| `ALLOWED_ORIGINS` | csv | _(leer)_ | Explizit erlaubte CORS-Origin(s) für Browser-Clients. | — |
| `FEATURE_UNIFIED_ERROR_FORMAT` | bool | `true` | Aktiviert den globalen Fehler-Envelope (`ok`/`error`). | — |
| `ERRORS_DEBUG_DETAILS` | bool | `false` | Ergänzt Fehlerantworten um Debug-ID/Hints – nur in geschützten Dev-Umgebungen setzen. | — |

#### Observability & Caching

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `HEALTH_DB_TIMEOUT_MS` | int | `500` | Timeout des Readiness-Datenbankchecks. | — |
| `HEALTH_DEP_TIMEOUT_MS` | int | `800` | Timeout je externem Dependency-Check (parallelisiert). | — |
| `HEALTH_DEPS` | csv | _(leer)_ | Liste benannter Abhängigkeiten (`spotify`, `slskd`, …) für die Readiness-Ausgabe. | — |
| `HEALTH_READY_REQUIRE_DB` | bool | `true` | Bei `false` wird Readiness auch ohne DB-Verbindung als `ok` gemeldet. | — |
| `CACHE_ENABLED` | bool | `true` | Aktiviert die Response-Cache-Middleware (`ConditionalCacheMiddleware`). | — |
| `CACHE_DEFAULT_TTL_S` | int | `30` | Standard-TTL (Sekunden) für gecachte Antworten. | — |
| `CACHE_STALE_WHILE_REVALIDATE_S` | int | `60` | Dauer des `stale-while-revalidate`-Fensters. | — |
| `CACHE_MAX_ITEMS` | int | `5000` | Maximale Einträge im In-Memory-LRU-Cache. | — |
| `CACHE_FAIL_OPEN` | bool | `true` | Liefert bei Cache-Fehlern die originale Response (Fail-Open). | — |
| `CACHEABLE_PATHS` | string | _(leer)_ | Optionale Regeln `pfad|ttl|stale`; Pfade werden automatisch mit `API_BASE_PATH` normalisiert. | — |
| `CACHE_STRATEGY_ETAG` | string | `strong` | Art der ETag-Berechnung (`strong`/`weak`). | — |
| `CACHE_WRITE_THROUGH` | bool | `true` | Invalidiert Spotify-Playlist-Routen unmittelbar nach Persistierung. | — |
| `CACHE_LOG_EVICTIONS` | bool | `true` | Steuert `cache.evict`-Logs für gezielte Invalidierungen. | — |
| `SECRET_VALIDATE_TIMEOUT_MS` | int | `800` | Timeout für Live-Secret-Validierungen (Spotify/slskd). | — |
| `SECRET_VALIDATE_MAX_PER_MIN` | int | `3` | Rate-Limit (Requests/min) pro Provider für Secret-Prüfungen. | — |

#### Integrationen & externe Dienste

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `SPOTIFY_CLIENT_ID` | string | _(leer)_ | OAuth Client-ID für den PRO-Modus. | 🔒 |
| `SPOTIFY_CLIENT_SECRET` | string | _(leer)_ | OAuth Client-Secret – niemals ins Repo. | 🔒 |
| `SPOTIFY_REDIRECT_URI` | string | _(leer)_ | Registrierte Redirect-URI für den OAuth-Flow. | — |
| `SPOTIFY_SCOPE` | string | `user-library-read playlist-read-private playlist-read-collaborative` | Angeforderte OAuth-Scopes. | — |
| `INTEGRATIONS_ENABLED` | csv | `spotify,slskd` | Aktivierte Provider (z. B. `spotify,slskd`). | — |
| `SLSKD_BASE_URL` | string | `http://127.0.0.1:5030` | Basis-URL für slskd (`SLSKD_URL` bzw. `SLSKD_HOST`/`SLSKD_PORT` werden weiterhin unterstützt). | — |
| `SLSKD_API_KEY` | string | _(leer)_ | API-Key für slskd. | 🔒 |
| `SPOTIFY_TIMEOUT_MS` | int | `15000` | Timeout für Spotify-API-Aufrufe. | — |
| `PLEX_TIMEOUT_MS` | int | `15000` | Timeout für Plex-Integrationen (archiviert). | — |
| `SLSKD_TIMEOUT_MS` | int | `8000` | Timeout für slskd-Anfragen. | — |
| `SLSKD_RETRY_MAX` | int | `3` | Neuversuche pro slskd-Request. | — |
| `SLSKD_RETRY_BACKOFF_BASE_MS` | int | `250` | Basis für exponentielles Backoff bei slskd. | — |
| `SLSKD_JITTER_PCT` | int | `20` | Zufälliger ±Jitter (in %) für das Backoff pro Versuch. | — |
| `SLSKD_PREFERRED_FORMATS` | csv | `FLAC,ALAC,APE,MP3` | Ranking-Priorisierung für Audioformate. | — |
| `SLSKD_MAX_RESULTS` | int | `50` | Maximale Treffer pro slskd-Suche. | — |
| `PROVIDER_MAX_CONCURRENCY` | int | `4` | Parallele Provider-Aufrufe (Spotify/slskd). | — |

##### Spotify OAuth (PRO-Modus)

- PRO-Funktionen werden automatisch aktiviert, sobald `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` und `SPOTIFY_REDIRECT_URI`
  hinterlegt sind. Die Werte stammen aus der Spotify Developer Console (App → _Settings_) und dürfen nicht eingecheckt
  werden. Der aktuelle Zustand lässt sich über `GET /spotify/status` prüfen.
- `SPOTIFY_REDIRECT_URI` muss exakt mit der in Spotify registrierten Redirect-URI übereinstimmen (inkl. Protokoll/Port). Für
  lokale Tests bietet sich z. B. `http://localhost:3000/api/auth/spotify/callback` an.
- Optional können die Secrets auch über `/settings` in die Datenbank geschrieben werden. ENV-Werte dienen als Fallback bzw.
  Initialbefüllung.

##### slskd (Soulseek-Daemon)

- `SLSKD_BASE_URL` verweist auf die HTTP-Instanz (Default `http://localhost:5030`). Legacy-Varianten (`SLSKD_URL`, Host/Port)
  werden weiterhin gelesen, sollten aber migriert werden.
- `SLSKD_API_KEY` **muss** konfiguriert werden und wird per `X-API-Key` Header übertragen.
- `SLSKD_JITTER_PCT` steuert den ±Jitter für das exponentielle Backoff (Default ±20 %).
- Zeitkritische Pfade verwenden `SLSKD_TIMEOUT_MS` sowie die Retry-Parameter `SLSKD_RETRY_MAX`/`SLSKD_RETRY_BACKOFF_BASE_MS`.
  Bei hohen Latenzen empfiehlt sich ein Timeout ≥ 8000 ms sowie ein konservatives Retry-Limit.

#### Artwork & Lyrics

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `ENABLE_ARTWORK` | bool | `false` | Aktiviert Artwork-Worker & `/soulseek/download/*/artwork`. | — |
| `ENABLE_LYRICS` | bool | `false` | Aktiviert Lyrics-Worker & zugehörige Endpunkte. | — |
| `ARTWORK_DIR` | path | `./artwork` | Cache-Verzeichnis für Coverdateien (`HARMONY_ARTWORK_DIR` Alias). | — |
| `ARTWORK_HTTP_TIMEOUT` | float | `15.0` | Timeout für Cover-Downloads (`ARTWORK_TIMEOUT_SEC`). | — |
| `ARTWORK_MAX_BYTES` | int | `10485760` | Maximale Covergröße (10 MiB). | — |
| `ARTWORK_WORKER_CONCURRENCY` | int | `2` | Gleichzeitige Artwork-Jobs (`ARTWORK_CONCURRENCY`). | — |
| `ARTWORK_MIN_EDGE` | int | `1000` | Mindestkante in Pixeln für Embeds. | — |
| `ARTWORK_MIN_BYTES` | int | `150000` | Mindestgröße (Bytes) für „hochauflösende“ Embeds. | — |
| `ARTWORK_FALLBACK_ENABLED` | bool | `false` | Aktiviert MusicBrainz/Cover Art Archive als Fallback. | — |
| `ARTWORK_FALLBACK_PROVIDER` | string | `musicbrainz` | Unterstützter Fallback-Provider. | — |
| `ARTWORK_FALLBACK_TIMEOUT_SEC` | float | `12.0` | Timeout für Fallback-Downloads. | — |
| `ARTWORK_FALLBACK_MAX_BYTES` | int | `10485760` | Maximale Dateigröße für Fallback-Downloads. | — |
| `MUSIXMATCH_API_KEY` | string | _(leer)_ | Optionaler API-Key für Lyrics-Fallback. | 🔒 |

#### Ingest, Backfill & Suche

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `FREE_IMPORT_MAX_LINES` | int | `200` | Max. Zeilen für den FREE-Import aus Textquellen. | — |
| `FREE_IMPORT_MAX_FILE_BYTES` | int | `1048576` | Max. Upload-Größe für FREE-Import-Dateien. | — |
| `FREE_IMPORT_MAX_PLAYLIST_LINKS` | int | `1000` | Max. Playlist-Links pro FREE-Request. | — |
| `FREE_IMPORT_HARD_CAP_MULTIPLIER` | int | `10` | Sicherheitsfaktor gegen oversized Inputs. | — |
| `FREE_ACCEPT_USER_URLS` | bool | `false` | Erlaubt benutzerdefinierte URLs im FREE-Modus. | — |
| `FREE_MAX_PLAYLISTS` | int | `100` | Max. Playlists pro FREE-Ingest-Job. | — |
| `FREE_MAX_TRACKS_PER_REQUEST` | int | `5000` | Track-Limit pro FREE-Anfrage. | — |
| `FREE_BATCH_SIZE` | int | `500` | Batchgröße für FREE-Jobs. | — |
| `INGEST_BATCH_SIZE` | int | `500` | Batchgröße beim Enqueue in die Download-Queue. | — |
| `INGEST_MAX_PENDING_JOBS` | int | `100` | Backpressure-Grenze für offene Ingest-Jobs. | — |
| `BACKFILL_MAX_ITEMS` | int | `2000` | Maximale Items pro Backfill-Lauf. | — |
| `BACKFILL_CACHE_TTL_SEC` | int | `604800` | TTL (Sekunden) für den Spotify-Suche-Cache. | — |
| `SEARCH_TIMEOUT_MS` | int | `8000` | Timeout für `/search`. | — |
| `SEARCH_MAX_LIMIT` | int | `100` | Maximale Treffer pro Seite. | — |

#### Worker, Queueing & Storage

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `WATCHLIST_INTERVAL` | int | `86400` | Wartezeit in Sekunden zwischen zwei Watchlist-Runs. | — |
| `WATCHLIST_MAX_CONCURRENCY` | int | `3` | Parallele Artists pro Tick (1–10). | — |
| `WATCHLIST_MAX_PER_TICK` | int | `20` | Bearbeitete Artists pro Tick. | — |
| `WATCHLIST_SPOTIFY_TIMEOUT_MS` | int | `8000` | Timeout für Spotify-Aufrufe in der Watchlist. | — |
| `WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS` | int | `12000` | Timeout für Soulseek-Suchen (Alias `WATCHLIST_SEARCH_TIMEOUT_MS`). | — |
| `WATCHLIST_TICK_BUDGET_MS` | int | `8000` | Budget pro Verarbeitungsschritt. | — |
| `WATCHLIST_BACKOFF_BASE_MS` | int | `250` | Basiswert für den Backoff bei Fehlern. | — |
| `WATCHLIST_RETRY_MAX` | int | `3` | Retries pro Tick vor Eskalation. | — |
| `WATCHLIST_RETRY_BUDGET_PER_ARTIST` | int | `6` | Gesamtretry-Budget pro Artist innerhalb des Cooldowns (Fallback, wenn kein Artist-Override gesetzt ist). | — |
| `ARTIST_MAX_RETRY_PER_ARTIST` | int | `6` | Override für das Retry-Budget einzelner Artists; ersetzt den Watchlist-Wert und wird auf `[1, 20]` begrenzt. | — |
| `WATCHLIST_COOLDOWN_MINUTES` | int | `15` | Pause nach fehlerhaften Läufen. | — |
| `ARTIST_COOLDOWN_S` | int | `900` | Sekundenbasierter Cooldown pro Artist; wird auf Minuten gerundet und überschreibt den Minutenwert. | — |
| `WATCHLIST_DB_IO_MODE` | string | `thread` | Datenbankmodus (`thread` oder `async`). | — |
| `WATCHLIST_JITTER_PCT` | float | `0.2` | Zufallsjitter für Backoff-Delays. | — |
| `WATCHLIST_SHUTDOWN_GRACE_MS` | int | `2000` | Grace-Periode beim Shutdown. | — |
| `WATCHLIST_TIMER_ENABLED` | bool | `true` | Aktiviert den periodischen WatchlistTimer (siehe Orchestrator). | — |
| `WATCHLIST_TIMER_INTERVAL_S` | float | `900` | Zielintervall in Sekunden zwischen zwei Timer-Ticks (≥0). | — |
| `WORKERS_ENABLED` | bool | `true` | Globaler Schalter, der sämtliche Hintergrund-Worker deaktiviert, wenn `false`. | — |
| `WORKER_MAX_CONCURRENCY` | int | `2` | Obergrenze für parallele Worker-Jobs (Fallback, wenn Worker-spezifische Werte fehlen). | — |
| `MATCHING_EXECUTOR_MAX_WORKERS` | int | `2` | Maximalthreads für CPU-lastiges Matching innerhalb des Executors. | — |
| `EXTERNAL_TIMEOUT_MS` | int | `10000` | Standard-Timeout für externe Aufrufe (Spotify, slskd), sofern keine Spezialspezifikation vorliegt. | — |
| `EXTERNAL_RETRY_MAX` | int | `3` | Maximalzahl an Retries bei transienten Abhängigkeiten. | — |
| `EXTERNAL_BACKOFF_BASE_MS` | int | `250` | Basiswert für exponentiellen Backoff externer Aufrufe. | — |
| `EXTERNAL_JITTER_PCT` | float | `20` | Zufallsjitter (±%) für Backoff-Delays; Werte `≤ 1` werden als Faktor interpretiert. | — |
| `WORKER_VISIBILITY_TIMEOUT_S` | int | `60` | Lease-Dauer, die beim Enqueue von Jobs als Default in das Payload geschrieben wird; sollte mit `ORCH_VISIBILITY_TIMEOUT_S` harmonieren. | — |
| `SYNC_WORKER_CONCURRENCY` | int | `2` | Parallele Downloads (kann via Setting überschrieben werden). | — |
| `RETRY_MAX_ATTEMPTS` | int | `10` | Max. automatische Neuversuche je Download. | — |
| `RETRY_BASE_SECONDS` | float | `60` | Grundverzögerung für Download-Retries. | — |
| `RETRY_JITTER_PCT` | float | `0.2` | Jitter-Faktor für Download-Retries. | — |
| `RETRY_POLICY_RELOAD_S` | float | `10` | TTL (Sekunden) für den gecachten Retry-Policy-Snapshot des Providers. | — |
| `RETRY_SCAN_INTERVAL_SEC` | float | `60` | Intervall der Retry-Scans. | — |
| `RETRY_SCAN_BATCH_LIMIT` | int | `100` | Limit pro Retry-Scan. | — |
| `MATCHING_WORKER_BATCH_SIZE` | int | `10` | Batchgröße des Matching-Workers (Default aus Settings). | — |
| `MATCHING_CONFIDENCE_THRESHOLD` | float | `0.65` | Mindest-Score zum Persistieren eines Matches. | — |
| `FEATURE_MATCHING_EDITION_AWARE` | bool | `true` | Aktiviert editionsbewusstes Album-Matching. | — |
| `MATCH_FUZZY_MAX_CANDIDATES` | int | `50` | Kandidatenlimit für fuzzy Matching. | — |
| `MATCH_MIN_ARTIST_SIM` | float | `0.6` | Mindest-Künstler-Similarität. | — |
| `MATCH_COMPLETE_THRESHOLD` | float | `0.9` | Schwelle für Albumstatus `complete`. | — |
| `MATCH_NEARLY_THRESHOLD` | float | `0.8` | Schwelle für `nearly complete`. | — |
| `DLQ_PAGE_SIZE_DEFAULT` | int | `25` | Standard-`page_size` der DLQ-Liste. | — |
| `DLQ_PAGE_SIZE_MAX` | int | `100` | Obergrenze für `page_size`. | — |
| `DLQ_REQUEUE_LIMIT` | int | `500` | Limit für Bulk-Requeue. | — |
| `DLQ_PURGE_LIMIT` | int | `1000` | Limit für Bulk-Purge. | — |
| `MUSIC_DIR` | path | `./music` | Zielpfad für organisierte Downloads. | — |

> **Retry-Provider:** `RetryPolicyProvider` lädt die Backoff-Parameter (`RETRY_*`) zur Laufzeit aus der Umgebung, cached sie für `RETRY_POLICY_RELOAD_S` Sekunden (Default 10 s) und unterstützt Job-spezifische Overrides (`RETRY_SYNC_MAX_ATTEMPTS`, `RETRY_MATCHING_BASE_SECONDS`, …). `get_retry_policy(<job_type>)` liefert Snapshots für Orchestrator/Worker, `SyncWorker.refresh_retry_policy()` invalidiert den Cache ohne Neustart.

> **Hinweis:** Spotify- und slskd-Zugangsdaten können über `/settings` in der Datenbank persistiert werden. Beim Laden der Anwendung haben Datenbankwerte Vorrang vor Umgebungsvariablen; ENV-Variablen dienen als Fallback und Basis für neue Deployments. Eine ausführliche Laufzeitreferenz inkl. Überschneidungen mit Datenbank-Settings befindet sich in [`docs/ops/runtime-config.md`](docs/ops/runtime-config.md).

### Orchestrator & Queue-Steuerung

Harmony bündelt alle Hintergrundjobs in einem Orchestrator, der die Queue priorisiert, Leases erneuert und periodische Watchlist-Ticks kontrolliert. Der Orchestrator ersetzt die früheren Worker-Runner und stellt reproduzierbare Start/Stop-Sequenzen bereit.

**Komponenten**

- **Scheduler** (`app/orchestrator/scheduler.py`) liest `queue_jobs`, sortiert sie nach konfigurierbaren Prioritäten und leased sie mit einem gemeinsamen Sichtbarkeits-Timeout. Stop-Signale werden über Ereignisse propagiert, sodass der Scheduler ohne Race-Conditions endet. Bei Leerlauf erhöht ein Backoff die Polling-Intervalle bis zum in `ORCH_POLL_INTERVAL_MAX_MS` gesetzten Limit, wodurch Datenbank-Last reduziert wird.
- **Dispatcher** (`app/orchestrator/dispatcher.py`) respektiert globale und Pool-bezogene Parallelitätsgrenzen, startet Handler pro Job-Typ und pflegt Heartbeats. Jeder Lauf emittiert strukturierte `event=orchestrator.*` Logs für Schedule-, Lease-, Dispatch- und Commit-Phasen.
- **WatchlistTimer** (`app/orchestrator/timer.py`) triggert periodisch neue Watchlist-Jobs, respektiert dabei dieselben Stop-Events und wartet beim Shutdown auf laufende Ticks. Das verhindert, dass nach einem Shutdown noch neue Artists eingeplant werden.

**Sichtbarkeit & Heartbeats**

- Scheduler und Dispatcher teilen sich eine Lease-Dauer: `ORCH_VISIBILITY_TIMEOUT_S` setzt die Leasing-Zeit beim Abruf aus der Queue, während `WORKER_VISIBILITY_TIMEOUT_S` weiterhin die Default-Lease beim Enqueue bestimmt. Beide Werte sollten konsistent bleiben, insbesondere für langlaufende Downloads.
- Während der Ausführung sendet der Dispatcher Heartbeats im 50 %-Intervall der aktuellen Lease (`lease_timeout_seconds * 0.5`). Die Heartbeats verlängern das Lease per `persistence.heartbeat()` und melden „lost“-Events, wenn ein Lease unerwartet abläuft.

**Timer-Verhalten**

- Der WatchlistTimer startet nur, wenn `WATCHLIST_INTERVAL` > 0 und der Feature-Flag aktiv ist. Ein Shutdown löst ein Stop-Event aus, wartet die in `WATCHLIST_SHUTDOWN_GRACE_MS` definierte Grace-Periode ab und bricht laufende Tasks andernfalls hart ab. Busy-Ticks werden übersprungen (`status="skipped"`, `reason="busy"`).
- Erfolgreiche Läufe protokollieren Anzahl der geladenen Artists, eingeplante Jobs sowie Fehler. Bei deaktiviertem Timer sendet der Orchestrator ein `status="disabled"`-Event – nützlich für Diagnose in Read-only-Setups.

#### Orchestrator-Variablen

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `ORCH_PRIORITY_JSON` | json | _(leer)_ | Optionales Mapping `job_type → priority`. JSON besitzt Vorrang vor CSV. | — |
| `ORCH_PRIORITY_CSV` | string | `sync:100,matching:90,retry:80,watchlist:50` | Fallback für Prioritäten (`job:score`). Unbekannte Job-Typen werden ignoriert. | — |
| `ORCH_POLL_INTERVAL_MS` | int | `200` | Minimales Warteintervall zwischen Scheduler-Ticks (mindestens 10 ms). | — |
| `ORCH_POLL_INTERVAL_MAX_MS` | int | `2000` | Obergrenze für das dynamisch hochgeregelte Scheduler-Intervall bei Leerlauf. | — |
| `ORCH_VISIBILITY_TIMEOUT_S` | int | `60` | Lease-Dauer beim Leasing aus der Queue (Minimum 5 s). | — |
| `ORCH_GLOBAL_CONCURRENCY` | int | `8` | Globale Obergrenze paralleler Dispatcher-Tasks. | — |
| `ORCH_HEARTBEAT_S` | int | `20` | Zielintervall für Dispatcher-Heartbeats (greift zusätzlich zur 50%-Lease-Regel). | — |
| `ORCH_POOL_<JOB>` | int | `sync=4`, `matching=4`, `retry=2`, `watchlist=2` | Optionale per-Job-Limits (z. B. `ORCH_POOL_SYNC=3`). Fällt ohne Wert auf das globale Limit zurück. | — |
| `ARTIST_POOL_CONCURRENCY` | int | `2` | Gemeinsames Limit für `artist_refresh`- und `artist_delta`-Pools; überschreibt die Einzelwerte. | — |
| `ARTIST_PRIORITY` | int | `50` | Setzt eine einheitliche Priorität für Artist-Jobs und überschreibt `ORCH_PRIORITY_*`. | — |
| `ARTIST_CACHE_INVALIDATE` | bool | `false` | Aktiviert Cache-Hints & Invalidierung für Artist-Workflows im Orchestrator. | — |

### Background Workers

Eine kuratierte Übersicht der Worker-Defaults, Environment-Variablen und Beispiel-Profile findet sich in [`docs/workers.md`](docs/workers.md). Beim Applikationsstart wird zusätzlich ein strukturiertes Log-Event `worker.config` geschrieben (`component="bootstrap"`), das die aktiven Parameter ohne Secrets ausgibt.

### Frontend-Umgebungsvariablen (Vite)

| Variable | Typ | Default | Beschreibung | Sicherheit |
| --- | --- | --- | --- | --- |
| `VITE_API_BASE_URL` | string | `http://127.0.0.1:8000` | Basis-URL des Backends ohne Pfadanteil. | — |
| `VITE_API_BASE_PATH` | string | _(leer)_ | Optionales Präfix für alle REST-Aufrufe (z. B. `/api`). | — |
| `VITE_API_TIMEOUT_MS` | int | `8000` | Timeout (in Millisekunden) für HTTP-Requests des Frontends. | — |
| `VITE_USE_OPENAPI_CLIENT` | bool | `false` | Aktiviert den optionalen OpenAPI-Client (falls generiert). | — |
| `VITE_REQUIRE_AUTH` | bool | `false` | Blockt Frontend-Requests ohne API-Key. | — |
| `VITE_AUTH_HEADER_MODE` | `x-api-key`\|`bearer` | `x-api-key` | Wählt den HTTP-Header für den Key. | — |
| `VITE_API_KEY` | string | _(leer)_ | Optionaler Build-Time-Key für lokale Entwicklung. | 🔒 |
| `VITE_LIBRARY_POLL_INTERVAL_MS` | int | `15000` | Pollintervall (ms) für Library-Tab & Watchlist. | — |
| `VITE_RUNTIME_API_KEY` | string | _(leer)_ | Optionaler Key, der zur Laufzeit via `window.__HARMONY_RUNTIME_API_KEY__` gesetzt wird. | 🔒 |

### Beispiel `.env`

```bash
# Auszug; vollständige Liste siehe `.env.example`
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/harmony
HARMONY_API_KEYS=local-dev-key
FEATURE_REQUIRE_AUTH=false
WATCHLIST_MAX_CONCURRENCY=3
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_AUTH_HEADER_MODE=x-api-key
```

### Health- und Readiness-Endpunkte

- `GET /api/v1/health` liefert einen liveness-Check ohne externes I/O und benötigt keinen API-Key (Allowlist). Beispiel:

  ```json
  { "ok": true, "data": { "status": "up", "version": "1.4.0", "uptime_s": 123.4 }, "error": null }
  ```

- `GET /api/v1/ready` prüft Datenbank, deklarierte Dependencies und den
  Migrationsstatus. Erfolgsantwort:

  ```json
  {
    "ok": true,
    "data": {
      "db": "up",
      "deps": { "spotify": "up" },
      "migrations": { "up_to_date": true, "current": "<rev>", "head": ["<rev>"] }
    },
    "error": null
  }
  ```

  Bei Störungen antwortet der Endpoint mit `503` und einem `DEPENDENCY_ERROR`, z. B.:

  ```json
  {
    "ok": false,
    "error": {
      "code": "DEPENDENCY_ERROR",
      "message": "not ready",
      "meta": {
        "db": "down",
        "deps": { "spotify": "down" },
        "migrations": { "up_to_date": false, "current": null, "head": ["<rev>"] }
      }
    }
  }
  ```


### Fehlerformat & OpenAPI

Alle Fehler folgen dem kanonischen Envelope und enthalten die Fehlercodes `VALIDATION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `DEPENDENCY_ERROR` oder `INTERNAL_ERROR`. Beispiel für eine abgewiesene Anfrage:

```json
{
  "ok": false,
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests.",
    "meta": { "retry_after_ms": 1200 }
  }
}
```

Das vollständige Schema steht über `${API_BASE_PATH}/openapi.json` bereit und wird automatisch in Swagger (`/docs`) sowie ReDoc (`/redoc`) gespiegelt. Änderungen am öffentlichen Vertrag müssen stets das OpenAPI-Gate passieren.

### API-Schicht

#### API-Struktur & Routen

- Die Domänenrouter leben unter `app/api/<domain>.py` (aktuell `search`, `spotify`, `system`) und werden über `router_registry.register_domain` konsistent unter dem API-Basis-Pfad `/api/v1` registriert.
- Die zentrale Registry `app/api/router_registry.py` fasst alle Domain- und Unterstützungsrouter zusammen und stellt `register_all(app, base_path, router=...)` bereit, um sie auf das FastAPI-Objekt zu montieren.
- Bestehende Router unter `app/routers/*` wurden auf schlanke Re-Exports reduziert und verweisen auf die neuen Domänenmodule.


- Domänenrouter liegen in `app/api/<domain>.py` (z. B. `spotify`, `search`, `system`, `watchlist` als optionales Modul) und kapseln die öffentlich erreichbaren Endpunkte. Legacy-Module in `app/routers/` dienen ausschließlich als Thin-Reexports.
- Der Watchlist-Endpunkt nutzt `app/services/watchlist_service.py`, um Datenbankzugriffe zu kapseln und strukturierte `service.call`-Events zu emittieren. Router arbeiten damit ausschließlich gegen Services statt rohe Sessions zu verwenden.
- `app/api/router_registry.py` registriert sämtliche Domain-Router und vergibt konsistente Prefixes sowie OpenAPI-Tags – Tests können die Liste zentral prüfen.
- `app/middleware/__init__.py` bündelt die komplette HTTP-Pipeline (Request-ID, Logging, optionale Auth/Rate-Limits, Cache, CORS/GZip, Error-Mapper).

### Middleware-Pipeline

- **CORS & GZip:** werden stets zuerst registriert und respektieren `CORS_ALLOWED_ORIGINS`, `CORS_ALLOWED_HEADERS`, `CORS_ALLOWED_METHODS` sowie `GZIP_MIN_SIZE` (Bytes).
- **Request-ID:** erzeugt bzw. propagiert `REQUEST_ID_HEADER` (Default `X-Request-ID`) und legt den Wert in `request.state.request_id` ab.
- **Logging:** emittiert strukturierte `api.request`-Events mit `duration_ms`, `status_code`, `method`, `path` und optional `entity_id` (Request-ID).
- **API-Key Auth:** nur aktiv, wenn `FEATURE_REQUIRE_AUTH=true`; Schlüssel stammen aus `HARMONY_API_KEYS` oder `HARMONY_API_KEYS_FILE` und werden über `Authorization: ApiKey <key>` oder `X-API-Key` übermittelt. Allowlist-Pfade lassen sich via `AUTH_ALLOWLIST` ergänzen.
- **Rate-Limiting:** optional (`FEATURE_RATE_LIMITING`), Token-Bucket pro `IP|Key|Route`; Parameter `RATE_LIMIT_BUCKET_CAP` und `RATE_LIMIT_REFILL_PER_SEC` steuern das Verhalten. Limit-Verstöße erzeugen `RATE_LIMITED`-Fehler inklusive `Retry-After`-Hinweisen.
- **Conditional Cache:** gesteuert über `CACHE_ENABLED`, `CACHE_DEFAULT_TTL_S`, `CACHE_MAX_ITEMS`, `CACHE_STRATEGY_ETAG` (`strong`/`weak`) und `CACHEABLE_PATHS` (Regex/CSV). `CACHE_WRITE_THROUGH` invalidiert Spotify-Playlist-Routen nach Persistierung, `CACHE_LOG_EVICTIONS` steuert strukturierte `cache.evict`-Logs. Unterstützt GET/HEAD, liefert ETags und 304-Antworten.
- **Error-Mapping:** zentral registriert; mappt Validation-, HTTP- und Dependency-Fehler konsistent auf `VALIDATION_ERROR`, `NOT_FOUND`, `DEPENDENCY_ERROR`, `RATE_LIMITED` oder `INTERNAL_ERROR`.

Beispielkonfiguration (dev-friendly Defaults):

```
FEATURE_REQUIRE_AUTH=false
FEATURE_RATE_LIMITING=false
CACHE_ENABLED=true
CACHEABLE_PATHS=/api/v1/library/.+
CACHE_DEFAULT_TTL_S=60
REQUEST_ID_HEADER=X-Request-ID
CORS_ALLOWED_ORIGINS=*
GZIP_MIN_SIZE=1024
```

### Auth, CORS & Rate Limiting

- Standardmäßig sind sowohl Authentifizierung (`FEATURE_REQUIRE_AUTH`) als auch globales Request-Limiting (`FEATURE_RATE_LIMITING`) deaktiviert. Wird Auth aktiviert, erwartet jede nicht allowlistete Route einen gültigen API-Key via `X-API-Key` oder `Authorization: ApiKey <key>`. Keys stammen aus ENV (`HARMONY_API_KEYS`) oder einer Datei (`HARMONY_API_KEYS_FILE`).
- Health-, Readiness-, Docs- und OpenAPI-Pfade werden automatisch freigestellt. Zusätzliche Pfade lassen sich über `AUTH_ALLOWLIST` definieren.
- `CORS_ALLOWED_ORIGINS`, `CORS_ALLOWED_HEADERS` und `CORS_ALLOWED_METHODS` kontrollieren CORS; leere Konfiguration blockiert Browser-Anfragen.
- Optionales globales Rate-Limiting wird per `FEATURE_RATE_LIMITING` aktiviert; `OPTIONS`-Requests und Allowlist-Pfade bleiben ausgenommen. Sensible Systempfade (`/system/secrets/*`) behalten zusätzlich ihr internes Limit `SECRET_VALIDATE_MAX_PER_MIN`.

### Logging & Observability

Harmony priorisiert strukturierte Logs. Ergänzend instrumentiert die Orchestrator-Pipeline Prometheus-Counter/Histogramme (z. B. `artist_scan_outcomes_total`, `artist_refresh_duration_seconds`). Die wichtigsten Event-Typen sind:

- `event=request`, ergänzt um `route`, `status`, `duration_ms` und optional `cache_status`.
- `event=worker_job`, ergänzt um `job_id`, `attempt`, `status`, `duration_ms`.
- `event=integration_call`, ergänzt um `provider`, `status`, `duration_ms`.

Weitere Logs nutzen stabile Felder wie `deps_up`/`deps_down` für Readiness-Auswertungen oder `auth.forbidden`/`cache.hit` zur Fehlersuche. Ergänzende Metadaten (`duration_ms`, `entity_id`, `key`, `path` etc.) variieren je nach Kontext.

Die Logs eignen sich für ELK-/Loki-Pipelines und bilden die alleinige Quelle für Betriebsmetriken. Details siehe [`docs/observability.md`](docs/observability.md).

### Performance & Zuverlässigkeit

- Worker-Last wird über `WATCHLIST_*`, `SYNC_WORKER_CONCURRENCY`, `RETRY_*` und `MATCHING_WORKER_*` feinjustiert. Die Defaults sind auf PostgreSQL-Pools abgestimmt; erhöhe Parallelität nur, wenn `max_connections`, I/O und Query-Pläne des Datenbankservers ausreichend Reserven bieten.
- Überwache bei Engpässen `pg_stat_activity`, `pg_locks` und `pg_stat_statements`, um Verbindungsengpässe und langsame SQL-Pfade frühzeitig zu erkennen. Harmonys Produktionsprofile rechnen mit mindestens 40 gleichzeitigen Sessions.
- Der Response-Cache (`CACHE_*`) reduziert Lesezugriffe und generiert korrekte `ETag`-/`Cache-Control`-Header. Bei Fehlern fällt er dank `CACHE_FAIL_OPEN` auf Live-Responses zurück.
- Backfill- und Ingest-Limits (`BACKFILL_MAX_ITEMS`, `FREE_*`, `INGEST_*`) verhindern Thundering-Herds und sichern deterministische Laufzeiten.
- Die Watchlist respektiert Timeouts (`WATCHLIST_SPOTIFY_TIMEOUT_MS`, `WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS`) sowie ein Retry-Budget pro Artist, damit Spotify/slskd nicht dauerhaft blockiert werden.
- Für Produktions-Setups empfiehlt sich der Betrieb hinter einem Reverse-Proxy, der zusätzlich TLS, Request-Limits und IP-Blocking übernimmt.

## API-Endpoints

Eine vollständige Referenz der FastAPI-Routen befindet sich in [`docs/api.md`](docs/api.md). Die wichtigsten Gruppen im Überblick:

- **Spotify** (`/spotify`): Status, Suche, Track-Details, Audio-Features, Benutzerbibliothek, Playlists, Empfehlungen.
- **Spotify FREE** (`/spotify/free`): Parser- und Enqueue-Endpunkte für importierte Titel ohne OAuth-Integration.
- **Soulseek** (`/soulseek`): Status, Suche, Downloads/Uploads, Warteschlangen, Benutzerverzeichnisse und -infos. Enthält `/soulseek/downloads/{id}/requeue` für manuelle Neuversuche und liefert Retry-Metadaten (`state`, `retry_count`, `next_retry_at`, `last_error`).
- **Matching** (`/matching`): Spotify↔Soulseek-Matching sowie Album-Matching (Legacy-Plex-Routen liefern `404`).
- **Settings** (`/settings`): Key-Value Einstellungen inkl. History.
- **Integrationen** (`/integrations`): Diagnose-Endpunkt mit aktivierten Providern und Health-Status.

### Spotify-Domäne (intern)

- **Service-Layer:** `SpotifyDomainService` bündelt Statusabfragen, Playlist-Operationen, FREE-Import und Backfill-Trigger in `app/services/spotify_domain_service.py`.
- **Router-Bündelung:** Spotify-Endpunkte werden im Sammelrouter `app/api/routers/spotify.py` registriert; die Legacy-Router delegieren lediglich.
- **Orchestrator-Anbindung:** FREE-Import- und Backfill-Flows nutzen ausschließlich die Orchestrator-Handler; direkte Worker-Initiierung aus Routern entfällt.

### Service-Schicht

- `IntegrationService` delegiert sämtliche Provider-Aufrufe an den `ProviderGateway` und hebt Fehler konsistent via `ServiceError` mit `ApiError`-Payload aus `app/schemas/errors.py` aus.
- `SearchService` orchestriert die Suche (Query → Gateway → Matching) und liefert `SearchResponse`-DTOs; der Matching-Score stammt aus dem `MusicMatchingEngine`.
- `LibraryService` verwaltet Bibliotheksdaten auf Basis der Pydantic-Provider-DTOs und liefert weiterhin Fuzzy-/LIKE-Suchen.
- Logging erfolgt über `log_event(..., event="service.call")` bzw. `event="service.cache"` mit `component=service.<name>` und strukturierten Feldern für Status, Dauer, Provider und Trefferanzahl.

Die frühere Plex-Integration wurde entfernt und wird im aktiven Build nicht geladen.

## Deprecations

- Die Legacy-Router unter `app.routers.*` sind lediglich Kompatibilitäts-Shims und werden zum
  **30.06.2025** entfernt. Verwendet stattdessen die neuen Module unter `app.api` (z. B.
  `app.api.search`, `app.api.spotify`, `app.api.routers.watchlist`). Beim Import warnen die Shims
  bereits heute über `DeprecationWarning`.

## Contributing

Erstellt neue Aufgaben über das Issue-Template ["Task (Codex-ready)"](./.github/ISSUE_TEMPLATE/task.md) und füllt die komplette [Task-Vorlage](docs/task-template.md) aus (inkl. FAST-TRACK/SPLIT_ALLOWED). Verweist im PR auf die ausgefüllte Vorlage und nutzt die bereitgestellte PR-Checkliste.

- **Datenbank-Checks beachten:** Führt vor neuen Schemaänderungen `alembic upgrade head` gegen eure PostgreSQL-Testinstanz sowie `pytest tests/migrations -q` aus. So bleibt sichergestellt, dass sämtliche Migrationen und Schutzprüfungen die PostgreSQL-Referenzimplementierung abdecken.

## Tests & CI

```bash
pytest
```

Die Tests mocken externe Dienste und können lokal wie auch via GitHub Actions ausgeführt werden. Für deterministische
Runs sollten die Worker mit `HARMONY_DISABLE_WORKERS=1` deaktiviert werden.

### PostgreSQL parity suite

- Alle Backend-Jobs in der CI – inkl. [`ci.yml`](.github/workflows/ci.yml) und [`backend-postgres.yml`](.github/workflows/backend-postgres.yml) – betreiben einen separaten PostgreSQL 16 Service, führen `alembic upgrade head` aus und lassen **die komplette** Test- und Lint-Matrix gegen die Datenbank laufen. Anschließend sorgt `alembic downgrade base` für den „downward compatibility“-Check.
- Lokal lässt sich der Lauf mit einem Docker-Container spiegeln:

  ```bash
  docker run --rm \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_DB=harmony \
    -p 5432:5432 postgres:16
  ```

  In einem zweiten Terminal:

  ```bash
  export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/harmony
  alembic upgrade head
  pytest -q
  alembic downgrade base
  ```

  Die Tests erzeugen pro Lauf isolierte Schemas (`search_path`) und räumen diese nach Abschluss automatisch auf.

## Lizenz

Das Projekt steht derzeit ohne explizite Lizenzdatei zur Verfügung. Ohne eine veröffentlichte Lizenz gelten sämtliche Rechte
als vorbehalten.
