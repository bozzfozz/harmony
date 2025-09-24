# Hintergrund-Worker

Harmony startet beim FastAPI-Startup mehrere Hintergrundprozesse, um langlaufende Aufgaben außerhalb des Request-Kontexts zu bearbeiten. Die Worker verwenden asynchrone Tasks (`asyncio`) und greifen über `session_scope()` auf die Datenbank zu.

## SyncWorker

- **Pfad:** `app/workers/sync_worker.py`
- **Aufgabe:** Verarbeitet Soulseek-Downloadjobs, startet Downloads über den `SoulseekClient` und aktualisiert den Fortschritt.
- **Arbeitsweise:**
  - Jobs werden in der Tabelle `worker_jobs` persistiert und beim Start wieder eingereiht. Angefangene Downloads überstehen dadurch Neustarts.
  - Mehrere Worker-Tasks ziehen parallel Jobs aus der Queue. Die Parallelität ist über Setting/ENV (`sync_worker_concurrency` bzw. `SYNC_WORKER_CONCURRENCY`) konfigurierbar.
  - Ein separater Poll-Loop ruft `refresh_downloads()` auf. Läuft kein aktiver Download, wird das Polling-Intervall automatisch auf den Idle-Wert hochgesetzt.
  - Health-/Monitoring-Informationen landen in der Settings-Tabelle (`worker.sync.last_seen`, `metrics.sync.*`).
- **Fehlerhandling:**
  - Fehlschläge beim Download markieren die betroffenen DB-Einträge als `failed` und werden im Activity Feed dokumentiert.
  - Unerwartete Statuswerte oder Fortschritte werden korrigiert; Netzwerkfehler beim Status-Polling erzeugen Warnungen, der Worker bleibt aktiv.

## MatchingWorker

- **Pfad:** `app/workers/matching_worker.py`
- **Aufgabe:** Nimmt Matching-Jobs (`spotify_track` + Kandidatenliste) entgegen und persistiert die besten Treffer.
- **Arbeitsweise:**
  - Jobs werden persistent in `worker_jobs` gespeichert. Beim Start lädt der Worker offene Jobs nach und verarbeitet sie in konfigurierbaren Batches (`matching_worker_batch_size`).
  - Jeder Kandidat wird gescored; alle Treffer oberhalb des Confidence-Thresholds (`matching_confidence_threshold`/`MATCHING_CONFIDENCE_THRESHOLD`) werden als `Match` gespeichert.
  - Nach jeder Charge entstehen Kennzahlen in der Settings-Tabelle (`metrics.matching.*`) sowie Activity-Einträge (`matching_batch`). Heartbeats stehen in `worker.matching.last_seen`.
- **Fehlerhandling:**
  - Ungültige Jobs werden mit `invalid_payload` markiert. Laufzeitfehler erzeugen Activity-Logs und setzen den Jobstatus in der DB auf `failed`.

## ScanWorker

- **Pfad:** `app/workers/scan_worker.py`
- **Aufgabe:** Pollt regelmäßig Plex-Statistiken und hält aggregierte Werte in den Settings aktuell.
- **Arbeitsweise:**
  - Intervall und Inkrementalscan lassen sich zur Laufzeit über Settings/ENV (`scan_worker_interval_seconds`, `scan_worker_incremental`) steuern.
  - Vor dem Statistikenlesen wird optional ein inkrementeller Plex-Scan per `refresh_library_section` ausgelöst.
  - Ergebnisse werden als Settings aktualisiert (`plex_*`) und mit Metriken versehen (`metrics.scan.interval`, `metrics.scan.duration_ms`). Heartbeats sowie Start/Stop-Zeitpunkte landen ebenfalls in der Settings-Tabelle.
- **Fehlerhandling:**
  - Wiederholte Scan-Fehler werden gezählt; nach drei Versuchen erzeugt der Worker einen Activity-Eintrag `scan_failed`. Netzwerkfehler verhindern keine späteren Läufe.

## AutoSyncWorker

- **Pfad:** `app/workers/auto_sync_worker.py`
- **Aufgabe:** Vergleicht täglich alle Spotify-Playlists und gespeicherten Tracks mit der Plex-Bibliothek, lädt fehlende Songs über Soulseek und importiert sie via Beets.
- **Arbeitsweise:**
  - Artist-Filter greifen weiterhin auf `artist_preferences` zurück. Tracks erhalten Prioritäten (Saved-Tracks/Favoriten, Popularität), womit Downloads bevorzugt nach Wichtigkeit gestartet werden.
  - Qualitätsregeln sind konfigurierbar (`autosync_min_bitrate`, `autosync_preferred_formats`). Nur Kandidaten, die diese Kriterien erfüllen, werden heruntergeladen – anderenfalls entsteht ein Activity-Eintrag `soulseek_low_quality`.
  - Fehlgeschlagene Soulseek-Suchen werden in `auto_sync_skipped_tracks` persistiert. Ab einer konfigurierbaren Anzahl (`skip_threshold`) werden Titel automatisch übersprungen.
  - Während des Laufs werden Teilfortschritte als Status zusammengefasst (z. B. Spotify ok, Plex ok, Soulseek failed). Metriken (`metrics.autosync.*`) und Heartbeats (`worker.autosync.last_seen`) landen in der Settings-Tabelle.
- **Fehlerhandling & Logging:**
  - Spotify/Plex-Ausfälle beenden den Lauf mit `status="partial"`; Soulseek-Probleme werden granular unterschieden (Suchfehler, Qualitätsfilter, Download-/Importfehler) und im Activity Feed protokolliert.
  - Erfolgreiche Downloads löschen den Skip-State, damit spätere Läufe nicht hängen bleiben.

## Zusammenspiel der Worker

- **Heartbeats & Monitoring:** Jeder Worker aktualisiert `worker.<name>.last_seen` sowie Start-/Stop-Timestamps. Ergänzende Kennzahlen (z. B. `metrics.sync.jobs_completed`, `metrics.matching.saved_total`, `metrics.autosync.duration_ms`) dienen als Einstiegspunkt für externe Monitoring-Lösungen.
- **Graceful Restart:** Persistente Job-Queues (`worker_jobs`) gewährleisten, dass laufende Matching-/Sync-Aufgaben bei einem Neustart fortgesetzt werden.
- **Konfiguration:** Neue Settings erlauben Laufzeit-Tuning ohne Codeänderungen (z. B. Polling-Intervalle, Quality Rules, Confidence-Thresholds). Änderungen greifen unmittelbar bei den nächsten Worker-Zyklen.
