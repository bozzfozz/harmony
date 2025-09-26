## v1.0.1 — 2025-09-25
- Refine AGENTS.md: Commit-Hygiene, Branch-Regel ein Ziel, Testing-Erwartungen, Quality-Gates (ruff/black, eslint/prettier, bandit/npm audit), AI-Review-Pflicht, Lizenz-Header, TASK_ID- und Testnachweise-Pflicht.
- Update PR-Template: TASK_ID und Testnachweise verpflichtend.

# Changelog

## v1.x.x

- Smart Search v2 – `/search` bündelt Spotify-, Plex- und Soulseek-Ergebnisse in einem normalisierten Schema inklusive Score, Bitrate/Format, erweiterten Filtern (Typ, Genre, Jahr, Dauer, Explicit, Mindestbitrate, bevorzugte Formate, Soulseek-Username), Sortierung (`relevance`, `bitrate`, `year`, `duration`) und Pagination.
- High-Quality Artwork – Downloads enthalten automatisch eingebettete Cover in Originalauflösung. Artwork-Dateien werden pro `spotify_album_id` zwischengespeichert (konfigurierbar via `ARTWORK_DIR`) und beim Abschluss von Downloads in MP3/FLAC/MP4 eingebettet. Neue API-Endpunkte: `GET /soulseek/download/{id}/artwork` (liefert Bild oder `404`) und `POST /soulseek/download/{id}/artwork/refresh` (erneut einreihen). Download-Datensätze speichern die zugehörigen Spotify-IDs (`spotify_track_id`, `spotify_album_id`).
- File Organization – abgeschlossene Downloads werden automatisch nach `Artist/Album/Track` in den Musik-Ordner (`MUSIC_DIR`, Default `./music`) verschoben. Auch Alben ohne Metadaten landen in einem eigenen `<Unknown Album>`-Verzeichnis, Dateinamen werden normalisiert und Duplikate mit Suffixen (`_1`, `_2`, …) abgelegt. Der endgültige Pfad steht in der Datenbank (`downloads.organized_path`) sowie in `GET /soulseek/downloads` zur Verfügung.
- Rich Metadata – alle Downloads enthalten zusätzliche Tags (Genre, Komponist, Produzent, ISRC, Copyright), werden direkt in die Dateien geschrieben und lassen sich per `GET /soulseek/download/{id}/metadata` abrufen oder über `POST /soulseek/download/{id}/metadata/refresh` neu befüllen.
- Complete Discographies – gesamte Künstlerdiskografien können automatisch heruntergeladen und kategorisiert werden.
- Automatic Lyrics – Downloads enthalten jetzt synchronisierte `.lrc`-Dateien mit Songtexten aus der Spotify-API (Fallback Musixmatch/lyrics.ovh) samt neuen Endpunkten zum Abruf und Refresh.
- Artist Watchlist – neue Tabelle `watchlist_artists`, API-Endpunkte (`GET/POST/DELETE /watchlist`) sowie ein periodischer Worker, der neue Releases erkennt, fehlende Tracks via Soulseek lädt und an den SyncWorker übergibt. Konfigurierbar über `WATCHLIST_INTERVAL`.
- CI-Gates – Push/PR-Workflow führt Ruff, Black, Mypy, Pytest, Jest, TypeScript-Build und einen OpenAPI-Snapshot-Vergleich aus und sorgt damit für reproduzierbare Qualitätsprüfungen.
- Persistente Soulseek-Retries – Downloads behalten `retry_count`, `next_retry_at`, `last_error` und wechseln nach Überschreitung der Grenze in den Dead-Letter-Status. Ein neuer Retry-Scheduler re-enqueued fällige Jobs mit exponentiellem Backoff, und `/soulseek/downloads/{id}/requeue` erlaubt manuelle Neuversuche.
