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

## Zusammenspiel der Worker

- Alle Worker werden in `app/main.py` initialisiert, sofern `HARMONY_DISABLE_WORKERS` nicht auf `1` gesetzt ist.
- Die Worker teilen sich keine gemeinsamen Datenstrukturen; Synchronisation erfolgt ausschließlich über die Datenbank.
- Beim Application-Shutdown stoppt FastAPI jeden Worker kontrolliert (`stop()`), um laufende Tasks zu beenden und Queues zu räumen.
