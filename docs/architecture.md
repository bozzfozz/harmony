# Architekturübersicht

Die MVP-Slim-Version von Harmony fokussiert sich auf Spotify und Soulseek. Plex- und Beets-spezifische Module liegen im Verzeichnis [`archive/integrations/plex_beets/`](../archive/integrations/plex_beets/) und werden zur Laufzeit nicht geladen. Der aktive Codepfad besteht aus folgenden Bausteinen:

```text
+----------------------------+
|          Clients           |
| SpotifyClient, SoulseekClient |
+-------------+--------------+
              |
              v
+-------------+--------------+
|            Core            |
| MatchingEngine, Utilities  |
+-------------+--------------+
              |
              v
+-------------+--------------+
|           Routers          |
| Spotify / Soulseek / Search|
| Matching / Settings / Sync |
| Activity / Downloads / API |
+-------------+--------------+
              |
              v
+-------------+--------------+
|       Hintergrund-Worker   |
| Sync / Matching / Playlist |
| Artwork / Lyrics / Retry   |
| Watchlist / Metadata       |
+-------------+--------------+
              |
              v
+-------------+--------------+
|          Datenbank         |
| SQLAlchemy + SQLite        |
+----------------------------+
```

## Komponenten im Detail

### Core

- **SpotifyClient** (`app/core/spotify_client.py`): kapselt OAuth, Suche, Audio-Features, Playlists und Nutzerinformationen.
- **SoulseekClient** (`app/core/soulseek_client.py`): kommuniziert mit slskd (Downloads, Uploads, Userinfos, Warteschlangen).
- **MusicMatchingEngine** (`app/core/matching_engine.py`): berechnet Scores für Spotify↔Soulseek-Kandidaten.
- **Utilities** (`app/utils/*`): Normalisierung, Metadaten, Activity-Logging, Service-Health.

### Routers

FastAPI-Router kapseln die öffentliche API und werden in `app/main.py` registriert. Aktiv sind u. a.:

- `app/routers/spotify_router.py` & `app/routers/spotify_free_router.py`: Suche, Backfill, Free-Ingest, Playlist-APIs.
- `app/routers/soulseek_router.py`: Download- und Upload-Management, Warteschlangen, Status und Artefakt-Endpunkte.
- `app/routers/search_router.py`: Aggregierte Suche über Spotify und Soulseek.
- `app/routers/matching_router.py`: Persistiertes Matching (`/matching/spotify-to-soulseek`) inkl. Legacy-404-Checks für Plex.
- `app/routers/metadata_router.py`: Metadata-Refresh-Routen geben 503 zurück, solange die archivierten Integrationen deaktiviert bleiben.
- `app/routers/settings_router.py`, `app/routers/system_router.py`, `app/routers/health_router.py`, `app/routers/watchlist_router.py` und `app/routers/activity_router.py` decken Settings, Systemstatus, Health-Checks, Watchlist und Activity-Feed ab.

### Hintergrund-Worker

Der Lifespan startet zuerst den Orchestrator (Scheduler, Dispatcher, WatchlistTimer), der Queue-Jobs priorisiert, Heartbeats pflegt und Watchlist-Ticks kontrolliert. Anschließend werden – sofern `WORKERS_ENABLED` aktiv ist – die eigentlichen Worker registriert und vom Dispatcher anhand ihrer Job-Typen aufgerufen.

`app/main.py` initialisiert beim Lifespan folgende Worker (deaktivierbar via `HARMONY_DISABLE_WORKERS=1`):

- **SyncWorker** (`app/workers/sync_worker.py`): Steuert Soulseek-Downloads inkl. Retry-Strategie und Datei-Organisation.
- **MatchingWorker** (`app/workers/matching_worker.py`): Persistiert Matching-Jobs aus der Queue.
- **PlaylistSyncWorker** (`app/workers/playlist_sync_worker.py`): Aktualisiert Spotify-Playlists.
- **ArtworkWorker** (`app/workers/artwork_worker.py`): Lädt Cover in Originalauflösung und bettet sie ein.
- **LyricsWorker** (`app/workers/lyrics_worker.py`): Erstellt LRC-Dateien mit synchronisierten Lyrics.
- **MetadataWorker** (`app/workers/metadata_worker.py`): Reichert Downloads mit Spotify-Metadaten an.
- **BackfillWorker** (`app/workers/backfill_worker.py`): Ergänzt Free-Ingest-Items über Spotify-APIs.
- **WatchlistWorker** (`app/workers/watchlist_worker.py`): Überwacht gespeicherte Artists auf neue Releases.
- **RetryScheduler** (`archive/workers/retry_scheduler.py`, archiviert): Frühere Loop-Implementierung zur Planung fehlgeschlagener Downloads; wurde durch den neuen Orchestrator (Scheduler + Dispatcher) ersetzt.

Der frühere Scan-/AutoSync-Stack liegt vollständig im Archiv und wird im Systemstatus nicht mehr angezeigt.

### Datenbank & Persistenz

- **`app/db.py`** initialisiert SQLite und liefert `session_scope()` / `get_session()`.
- **`app/models.py`** definiert Tabellen wie `Playlist`, `Download`, `Match`, `Setting`, `SettingHistory`, `WatchlistArtist`.
- **`app/schemas.py` & `app/schemas_search.py`** beschreiben Pydantic-Modelle für Requests/Responses und Suchresultate.

### Datenfluss (vereinfacht)

1. **Ingest**: Spotify-Free-Uploads und API-Aufrufe landen als `ingest_jobs`/`ingest_items` in der Datenbank.
2. **Backfill**: Der Backfill-Worker reichert FREE-Daten mit Spotify-IDs, ISRC, Laufzeiten und Playlist-Expansion an.
3. **Soulseek Matching & Downloads**: MatchingWorker bewertet Kandidaten, SyncWorker lädt Dateien und aktualisiert Status.
4. **Postprocessing**: Artwork-, Lyrics- und Metadata-Worker ergänzen Metadaten und Artefakte; Datei-Organisation läuft im SyncWorker.
5. **Watchlist & Activity**: WatchlistWorker triggert neue Downloads, `activity_manager` zeichnet Events für UI/Automatisierungen auf.

### Observability & Wiring Guard

- Beim Start protokolliert `app/main.py` ein `wiring_summary` mit aktiven Routern, Workern und Integrationen (`plex=false`, `beets=false`).
- `scripts/audit_wiring.py` stellt sicher, dass keine Plex-/Beets-Referenzen außerhalb des Archivs in `app/` oder `tests/` landen und ist in der CI eingebunden.

### Archivierte Module

Legacy-Code (Plex-Router, Scan-Worker, AutoSync, Beets-CLI) befindet sich unter [`archive/integrations/plex_beets/`](../archive/integrations/plex_beets/) und kann separat wiederbelebt werden. Die aktiven Tests (`tests/test_matching.py`) verifizieren, dass entsprechende Endpunkte `404` liefern.
