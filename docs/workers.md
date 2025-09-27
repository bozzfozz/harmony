# Hintergrund-Worker (MVP-Slim)

Harmony startet mehrere asynchrone Worker, sobald die Anwendung initialisiert ist (`app/main.py`). Plex- und Beets-Worker sind archiviert und werden nicht geladen. Dieses Dokument fasst die aktiven Komponenten zusammen.

## Übersicht

| Worker | Datei | Aufgabe |
| ------ | ----- | ------- |
| SyncWorker | `app/workers/sync_worker.py` | Verarbeitet Soulseek-Downloads, führt Datei-Organisation aus und aktualisiert Retry-Informationen. |
| MatchingWorker | `app/workers/matching_worker.py` | Persistiert Matching-Jobs aus der Queue (`WorkerJob`). |
| PlaylistSyncWorker | `app/workers/playlist_sync_worker.py` | Synchronisiert Spotify-Playlists mit der Datenbank. |
| ArtworkWorker | `app/workers/artwork_worker.py` | Lädt Cover in höchster Auflösung, cached Dateien und bettet sie in Downloads ein. |
| LyricsWorker | `app/workers/lyrics_worker.py` | Erstellt `.lrc`-Dateien aus Spotify-Lyrics oder externen Quellen. |
| MetadataWorker | `app/workers/metadata_worker.py` | Ergänzt Metadaten (Genre, Komponist, Produzent, ISRC, Copyright). |
| BackfillWorker | `app/workers/backfill_worker.py` | Reichert FREE-Ingest-Daten mit Spotify-Informationen an. |
| WatchlistWorker | `app/workers/watchlist_worker.py` | Überwacht gespeicherte Artists auf neue Releases und stößt Downloads an. |
| RetryScheduler | `app/workers/retry_scheduler.py` | Plant fehlgeschlagene Downloads mit Backoff neu ein. |

## Lebenszyklus

- `HARMONY_DISABLE_WORKERS=1` deaktiviert alle Worker (nützlich für Tests oder read-only-Demos).
- Einzelne Feature-Flags: `ENABLE_ARTWORK` und `ENABLE_LYRICS` aktivieren Artwork-/Lyrics-Worker und zugehörige Endpunkte (Default: `false`).
- Beim Shutdown ruft Harmony `stop()` auf allen Worker-Instanzen auf (`app/main.py::_stop_background_workers`).

## Systemstatus & Observability

- `GET /status` zeigt Worker-Zustände (`running`, `stale`, `unavailable`) inklusive Queue-Größe für Matching und Sync.
- Der `wiring_summary`-Logeintrag beim Start listet aktive Worker auf.
- Activity-Events (`record_activity`) spiegeln wichtige Phasen wider (`sync_started`, `sync_completed`, `soulseek_no_results`, `artwork_embedded`, `lyrics_generated`).

## Archiv

Frühere Worker (`ScanWorker`, `AutoSyncWorker`, `DiscographyWorker`, Beets-Poststeps) liegen unter [`archive/integrations/plex_beets/`](../archive/integrations/plex_beets/). Die neue Wiring-Audit (`scripts/audit_wiring.py`) stellt sicher, dass sie nicht versehentlich erneut importiert werden.
