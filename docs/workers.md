# Hintergrund-Worker

Harmony startet beim FastAPI-Startup mehrere Hintergrundprozesse, um langlaufende Aufgaben außerhalb des Request-Kontexts zu
bearbeiten. Die Worker verwenden asynchrone Tasks (`asyncio`) und greifen über `session_scope()` auf die Datenbank zu.

## SyncWorker

- **Pfad:** `app/workers/sync_worker.py`
- **Aufgabe:** Verarbeitet Soulseek-Downloadjobs, startet Downloads über den `SoulseekClient` und aktualisiert den Fortschritt.
- **Arbeitsweise:**
  - Eingehende Jobs (Username + Datei-Metadaten) landen in einer `asyncio.Queue`.
  - Läuft der Worker, werden Jobs sequentiell aus der Queue geholt; andernfalls wird der Download sofort synchron abgewickelt.
  - Nach jedem Job wird `refresh_downloads()` aufgerufen, das `client.get_download_status()` pollt und DB-Einträge (`Download`)
    aktualisiert (Status, Fortschritt, `updated_at`).
- **Polling-Intervall:** 2 Sekunden Timeout beim Queue-Waiting; fällt kein Job an, wird in diesem Intervall der Status nachgezogen.
- **Fehlerhandling:**
  - Fehler beim Download markieren die betroffenen Einträge als `failed`.
  - Nicht erkannte Statuswerte werden verworfen, Fortschrittswerte werden auf `0…100` begrenzt.
  - Netzwerkfehler beim Status-Polling führen zu einem Warn-Log, ohne den Worker zu stoppen.

## MatchingWorker

- **Pfad:** `app/workers/matching_worker.py`
- **Aufgabe:** Nimmt Matching-Jobs (`spotify_track` + Kandidatenliste) entgegen und persistiert die besten Treffer.
- **Arbeitsweise:**
  - Verwendet eine `asyncio.Queue` und ein Flag, um Shutdowns kontrolliert zu verarbeiten.
  - Für `spotify-to-plex` ruft der Worker `MusicMatchingEngine.find_best_match()` auf.
  - Für alle anderen Jobs (z. B. `spotify-to-soulseek`) wird `calculate_slskd_match_confidence()` pro Kandidat berechnet und das
    höchste Scoring übernommen.
  - Die Ergebnisse werden als `Match`-Objekte gespeichert (`source`, `spotify_track_id`, `target_id`, `confidence`).
- **Fehlerhandling:**
  - Exceptions beim Abarbeiten werden geloggt; das Queue-Item wird dennoch als abgeschlossen markiert.
  - Ungültige Jobs (fehlende Kandidaten/Tracks) werden verworfen und mit Warnung protokolliert.

## ScanWorker

- **Pfad:** `app/workers/scan_worker.py`
- **Aufgabe:** Pollt regelmäßig Plex-Statistiken und hält aggregierte Werte in den Settings aktuell.
- **Arbeitsweise:**
  - Standardintervall: 600 Sekunden (`interval_seconds`-Parameter).
  - `get_library_statistics()` liefert Anzahl Artists/Albums/Tracks; zusätzlich wird ein Zeitstempel gesetzt.
  - Werte werden über `_upsert_setting` als `Setting`-Einträge geschrieben oder aktualisiert (`plex_artist_count`, `plex_album_count`,
    `plex_track_count`, `plex_last_scan`).
- **Fehlerhandling:**
  - Netzwerkfehler werden geloggt und führen zu keinem Update.
  - Der Worker toleriert `asyncio.CancelledError`, wenn er beim Shutdown gestoppt wird.

## AutoSyncWorker

- **Pfad:** `app/workers/auto_sync_worker.py`
- **Aufgabe:** Vergleicht täglich alle Spotify-Playlists und gespeicherten Tracks mit der Plex-Bibliothek, lädt fehlende Songs über Soulseek und importiert sie via Beets.
- **Arbeitsweise:**
  - Läuft standardmäßig alle 24 Stunden automatisch nach dem FastAPI-Startup (deaktivierbar über `HARMONY_DISABLE_WORKERS`).
  - Sammelt Spotify-Daten (`get_user_playlists`, `get_playlist_items`, `get_saved_tracks`) und führt einen Abgleich mit Plex-Track-Metadaten (`get_libraries`, `get_library_items`).
  - Für fehlende Titel wird eine Soulseek-Suche ausgelöst, der erste Treffer heruntergeladen und anschließend per `beet import` in die Bibliothek übernommen.
  - Nach erfolgreichen Imports wird `get_library_statistics()` aufgerufen, um Plex zu aktualisieren; alle Schritte landen im Activity Feed (`autosync_started`, `spotify_loaded`, `downloads_requested`, ...).
- **Fehlerhandling & Logging:**
  - Spotify/Plex-Ausfälle beenden den Lauf mit `status="partial"`, ohne den Worker zu stoppen; die Ursache wird geloggt und im Activity Feed dokumentiert.
  - Soulseek-Suchen ohne Ergebnis werden als `soulseek_no_results` markiert; Download- oder Importfehler führen zu Retries (3 Versuche mit wachsender Wartezeit).
  - Jeder Schritt schreibt über den Standard-Logger (`get_logger(__name__)`) und Aktivitäten werden chronologisch erfasst.
- **Manuelles Triggern:**
  - Über `POST /api/sync` lässt sich der Worker ad-hoc starten; das `source`-Flag in den Activity-Details unterscheidet geplante (`scheduled`) und manuelle Läufe (`manual`).

## Zusammenspiel der Worker

- Alle Worker werden in `app/main.py` initialisiert, sofern `HARMONY_DISABLE_WORKERS` nicht auf `1` gesetzt ist.
- Die Worker teilen sich keine gemeinsamen Datenstrukturen; Synchronisation erfolgt ausschließlich über die Datenbank.
- Beim Application-Shutdown stoppt FastAPI jeden Worker kontrolliert (`stop()`), um laufende Tasks zu beenden und Queues zu räumen.
