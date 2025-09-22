# Architekturübersicht

Die Harmony-Anwendung folgt einer modularen FastAPI-Architektur, die interne und externe Komponenten klar voneinander trennt.
Das folgende textuelle Diagramm beschreibt den Aufbau:

```
+----------------------------+
|          Clients           |
| SpotifyClient, PlexClient, |
| SoulseekClient, BeetsClient|
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
| Spotify / Plex / Soulseek  |
| Matching / Settings / Beets|
+------+------+-------------+
       |      |
       |      v
       |   Background Workers
       |   (Sync, Matching,   
       |    Scan, Playlist)   
       v                      
+------+------+-------------+
|        Datenbank           |
| SQLAlchemy Modelle         |
+----------------------------+
```

## Komponenten im Detail

### Core

- **SpotifyClient** (`app/core/spotify_client.py`): Kapselt die Spotify Web API (Suche, Audio Features, Playlists, Empfehlungen).
- **PlexClient** (`app/core/plex_client.py`): Async-Client für Bibliotheken, Sessions, Timeline und Live-TV.
- **SoulseekClient** (`app/core/soulseek_client.py`): Bindet den slskd-Daemon an und stellt Download-/Upload-Operationen bereit.
- **BeetsClient** (`app/core/beets_client.py`): Führt Beets CLI-Kommandos innerhalb eines Threadpools aus.
- **MusicMatchingEngine** (`app/core/matching_engine.py`): Berechnet Ähnlichkeitsscores und liefert Best-Match-Kandidaten.

### Routers

FastAPI-Router bilden die öffentliche REST-API. Jeder Router importiert die benötigten Clients als Dependencies (`app/dependencies.py`).
Beispiele:

- `app/routers/spotify_router.py` für `/spotify`-Endpunkte (Suche, Audio Features, Playlists, Benutzerprofil).
- `app/routers/plex_router.py` für `/plex`-Endpunkte (Bibliotheken, PlayQueues, Benachrichtigungen).
- `app/routers/soulseek_router.py` für `/soulseek`-Endpunkte (Downloads, Uploads, Benutzerinformationen).
- `app/routers/matching_router.py` für `/matching` (Spotify→Plex/Soulseek, Album-Matching).
- `app/routers/settings_router.py` für `/settings` (Key-Value Settings + Historie).
- `app/routers/beets_router.py` für `/beets` (Import, Query, Stats, Dateimanipulation).

### Datenbank

- `app/db.py` initialisiert SQLite und stellt `session_scope()` sowie `get_session()` bereit.
- `app/models.py` definiert SQLAlchemy-Modelle wie `Playlist`, `Download`, `Match`, `Setting`, `SettingHistory`.
- `app/schemas.py` enthält die Pydantic-Modelle für Anfragen und Antworten.

### Hintergrund-Worker

Während des Startup-Events (`app/main.py`) werden – sofern `HARMONY_DISABLE_WORKERS` nicht gesetzt ist – folgende Worker gestartet:

- **SyncWorker** (`app/workers/sync_worker.py`): Verarbeitet Soulseek-Downloadjobs und aktualisiert Fortschritte.
- **MatchingWorker** (`app/workers/matching_worker.py`): Persistiert berechnete Matches asynchron.
- **ScanWorker** (`app/workers/scan_worker.py`): Pollt Plex in Intervallen und aktualisiert Statistik-Settings.
- **PlaylistSyncWorker** (`app/workers/playlist_sync_worker.py`): Synchronisiert Spotify-Playlists in die Datenbank.

Alle Worker greifen über `session_scope()` auf die Datenbank zu und protokollieren Abläufe über `app/logging.py`.

## Synchronisations- & Matching-Prozesse

1. **Soulseek-Downloads**: REST-Aufrufe gegen `/soulseek/download` persistieren Downloads in der Datenbank und übergeben Jobs an den
   `SyncWorker`. Dieser startet Downloads über den `SoulseekClient` und pollt `get_download_status()`, um Fortschritt, Status und
   Zeitstempel (`Download.updated_at`) zu aktualisieren.
2. **Spotify-Playlist-Sync**: Der `PlaylistSyncWorker` ruft periodisch `SpotifyClient.get_user_playlists()` auf, normalisiert die
   Daten und speichert sie in der `Playlist`-Tabelle. Änderungen werden über `updated_at` erfasst.
3. **Plex-Scans**: Der `ScanWorker` pollt `PlexClient.get_library_statistics()` und schreibt aggregierte Werte in `Setting`-Einträge.
4. **Matching**: Der Matching-Router kann Ergebnisse direkt persistieren. Zusätzlich verarbeitet der `MatchingWorker` Jobs aus seiner
   Queue und speichert `Match`-Objekte. Die Matching-Engine vergleicht Spotify-Tracks mit Plex- oder Soulseek-Kandidaten und liefert
   Konfidenzwerte zurück.

## Interaktion der Komponenten

- Router lösen Aktionen aus und rufen über Dependencies die passenden Core-Clients auf.
- Core-Clients kommunizieren mit externen Diensten und liefern strukturierte Antworten.
- Worker laufen asynchron und nutzen dieselben Clients, um Automatisierungen im Hintergrund auszuführen.
- Alle Schreiboperationen gehen über SQLAlchemy-Sessions, sodass API-Aufrufe und Worker auf denselben Datenbestand zugreifen.
