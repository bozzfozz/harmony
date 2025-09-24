# API-Referenz

Die folgenden Tabellen geben einen Überblick über die wichtigsten REST-Endpunkte des Harmony-Backends. Beispiel-Requests orientieren
sich an den in `app/routers` definierten Routen. Alle Antworten sind JSON-codiert.

## System

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `GET` | `/status` | Liefert allgemeinen Backend-Status inklusive Worker-Informationen. |
| `GET` | `/api/system/stats` | Systemkennzahlen (CPU, RAM, Speicher, Netzwerk) über `psutil`. |

**Beispiel:**

```http
GET /status HTTP/1.1
```

```json
{
  "status": "ok",
  "version": "1.4.0",
  "uptime_seconds": 12.5,
  "workers": {
    "soulseek_sync": {"state": "idle", "queue_size": 0},
    "matching": {"state": "running"}
  }
}
```

## Metadata (`/api/metadata`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `POST` | `/api/metadata/update` | Startet den Metadaten-Refresh-Worker. |
| `GET` | `/api/metadata/status` | Aktueller Status inkl. Phase, Timestamps und Matching-Queue. |
| `POST` | `/api/metadata/stop` | Fordert einen Abbruch des laufenden Jobs an. |

**Beispiel:**

```http
POST /api/metadata/update HTTP/1.1
```

```json
{
  "message": "Metadata update started",
  "state": {
    "status": "running",
    "phase": "Preparing",
    "processed": 0,
    "matching_queue": 0
  }
}
```

## Sync & Suche (`/api`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `POST` | `/api/sync` | Startet einen manuellen Playlist-/Bibliotheksabgleich inkl. AutoSyncWorker. |
| `POST` | `/api/search` | Führt eine Quell-übergreifende Suche (Spotify/Plex/Soulseek) aus. |
| `GET` | `/api/downloads` | Listet Downloads mit `?limit`, `?offset` und optional `?all=true`. |
| `GET` | `/api/download/{id}` | Liefert Status, Fortschritt sowie Zeitstempel eines Downloads. |
| `POST` | `/api/download` | Persistiert Downloads und übergibt sie an den Soulseek-Worker. |
| `DELETE` | `/api/download/{id}` | Bricht einen laufenden Download ab und markiert ihn als `cancelled`. |
| `POST` | `/api/download/{id}/retry` | Startet einen neuen Transfer für fehlgeschlagene oder abgebrochene Downloads. |
| `GET` | `/api/activity` | Liefert den In-Memory-Aktivitätsfeed (max. 50 Einträge). |

**Beispiel:**

```http
POST /api/search HTTP/1.1
Content-Type: application/json

{"query": "Daft Punk"}
```

```json
{
  "query": "Daft Punk",
  "results": {
    "spotify": {"tracks": [...], "artists": [...], "albums": [...]},
    "soulseek": {"results": ["Daft Punk"]}
  }
}
```

> **Hinweis:** Ein `POST /api/sync` Durchlauf stößt zusätzlich den neuen AutoSyncWorker an. Dieser prüft Spotify-Playlists und gespeicherte Tracks, lädt fehlende Songs über Soulseek und importiert sie via Beets, bevor Plex-Statistiken aktualisiert werden. Alle Schritte erscheinen im Activity Feed.

**Download-Beispiel:**

**Download-Übersicht:**

Unterstützte Query-Parameter:

- `limit` (Default `20`, Maximum `100`): Anzahl der zurückgegebenen Downloads.
- `offset` (Default `0`): Startindex für Paging.
- `all` (Default `false`): `true` inkludiert auch abgeschlossene/fehlgeschlagene Einträge.

```http
GET /api/downloads HTTP/1.1
```

```json
{
  "downloads": [
    {
      "id": 42,
      "filename": "Daft Punk - Harder.mp3",
      "status": "queued",
      "progress": 0.0,
      "created_at": "2024-03-18T12:00:00Z",
      "updated_at": "2024-03-18T12:00:00Z"
    }
  ]
}
```

**Limitierte Übersicht (z. B. für Widgets):**

```http
GET /api/downloads?limit=5 HTTP/1.1
```

```json
{
  "downloads": [
    {
      "id": 7,
      "filename": "Daft Punk - One More Time.mp3",
      "status": "running",
      "progress": 65.0,
      "created_at": "2024-03-18T12:06:00Z",
      "updated_at": "2024-03-18T12:06:10Z"
    }
  ]
}
```

**Alle Downloads inklusive abgeschlossener/fehlgeschlagener Transfers:**

```http
GET /api/downloads?all=true HTTP/1.1
```

```json
{
  "downloads": [
    {
      "id": 42,
      "filename": "Daft Punk - Harder.mp3",
      "status": "completed",
      "progress": 100.0,
      "created_at": "2024-03-18T12:00:00Z",
      "updated_at": "2024-03-18T12:05:00Z"
    }
  ]
}
```

**Paging-Beispiel:**

```http
GET /api/downloads?limit=10&offset=10 HTTP/1.1
```

```json
{
  "downloads": [
    {
      "id": 31,
      "filename": "Daft Punk - Voyager.mp3",
      "status": "running",
      "progress": 35.0,
      "created_at": "2024-03-18T12:04:00Z",
      "updated_at": "2024-03-18T12:04:10Z"
    }
  ]
}
```

**Download-Details:**

```http
GET /api/download/42 HTTP/1.1
```

```json
{
  "id": 42,
  "filename": "Daft Punk - Harder.mp3",
  "status": "queued",
  "progress": 0.0,
  "created_at": "2024-03-18T12:00:00Z",
  "updated_at": "2024-03-18T12:05:00Z"
}
```

**Download-Abbruch:**

```http
DELETE /api/download/42 HTTP/1.1
```

```json
{
  "status": "cancelled",
  "download_id": 42
}
```

Harmony ruft bei jedem Abbruch die slskd-TransfersApi (`DELETE /transfers/downloads/{id}`) auf. Erst wenn der Daemon die Anfrage bestätigt, wird der Download in der Datenbank als `cancelled` markiert und der Activity Feed um einen Eintrag `download_cancelled` mit `download_id` und `filename` ergänzt. Sollte der Daemon nicht erreichbar sein, antwortet der Endpunkt mit `502 Bad Gateway` und der Status in der Datenbank bleibt unverändert.

**Download-Start:**

```http
POST /api/download HTTP/1.1
Content-Type: application/json

{
  "username": "dj_user",
  "files": [{"filename": "Daft Punk - Harder.mp3"}]
}
```

```json
{
  "status": "queued",
  "download_id": 42,
  "downloads": [
    {
      "id": 42,
      "filename": "Daft Punk - Harder.mp3",
      "status": "queued",
      "progress": 0.0,
      "created_at": "2024-03-18T12:00:00Z",
      "updated_at": "2024-03-18T12:00:00Z"
    }
  ]
}
```

**Download-Retry:**

```http
POST /api/download/42/retry HTTP/1.1
```

```json
{
  "status": "queued",
  "download_id": 87
}
```

Der Endpunkt akzeptiert nur Downloads im Status `failed` oder `cancelled`. Vor dem erneuten Start wird der ursprüngliche Job über `TransfersApi.cancel_download` beendet, anschließend werden `username`, `filename` und `filesize` erneut via `TransfersApi.enqueue` eingereiht. Dadurch entsteht ein neuer Download-Datensatz mit eigener ID, der Activity Feed erhält einen Eintrag `download_retried` mit `original_download_id`, `retry_download_id` und `filename`. Wenn slskd nicht erreichbar ist, wird der Vorgang mit `502 Bad Gateway` abgebrochen und kein neuer Datensatz erzeugt.

## Download-Widget im Dashboard

Das Dashboard zeigt aktive Downloads in einem kompakten Widget an. Die Komponente nutzt `GET /api/downloads` und pollt den Endpunkt alle 15 Sekunden, um Fortschritte automatisch zu aktualisieren. Bei mehr als fünf aktiven Transfers blendet das Widget einen "Alle anzeigen" Button ein, der direkt zur vollständigen Downloads-Ansicht navigiert.

**Beispielansicht:**

```
Aktive Downloads
┌──────────────────────────────┬──────────┬─────────────┬──────────────┐
│ Dateiname                    │ Status   │ Fortschritt │ Aktionen     │
├──────────────────────────────┼──────────┼─────────────┼──────────────┤
│ Track One.mp3                │ Running  │ 45 %        │ [Abbrechen]  │
│ Track Two.mp3                │ Failed   │ 0 %         │ [Neu starten]│
└──────────────────────────────┴──────────┴─────────────┴──────────────┘
Alle anzeigen → /downloads
```

**Activity-Beispiel:**

```http
GET /api/activity HTTP/1.1
```

```json
[
  {
    "timestamp": "2024-03-18T12:00:00Z",
    "type": "download",
    "status": "queued",
    "details": {"download_ids": [42], "username": "dj_user"}
  },
  {
    "timestamp": "2024-03-18T11:58:12Z",
    "type": "search",
    "status": "completed",
    "details": {"query": "Daft Punk", "sources": ["plex", "soulseek", "spotify"]}
  }
]
```

### Frontend-Oberfläche

![Downloads-Verwaltung](downloads-page.svg)

Die neue Downloads-Seite im Harmony-Frontend ermöglicht das Starten von Test-Downloads über eine beliebige Datei- oder Track-ID und zeigt aktive Transfers inklusive Status, Fortschrittsbalken und Erstellungszeitpunkt an. Über Tailwind- und shadcn/ui-Komponenten werden Ladezustände, Leerlaufmeldungen ("Keine Downloads aktiv") sowie Fehler-Toasts konsistent dargestellt. Jeder erfolgreich gestartete Download löst eine Bestätigungsmeldung aus, während fehlgeschlagene Anfragen klar hervorgehoben werden. Zusätzlich stehen pro Zeile Buttons zum sofortigen Abbrechen laufender Jobs sowie zum erneuten Start fehlgeschlagener oder abgebrochener Transfers bereit.

![Activity-Feed-Widget](activity-feed-widget.svg)

Auf dem Dashboard ergänzt das Activity-Feed-Widget die bestehenden Statuskacheln. Es pollt den `/api/activity`-Endpunkt alle zehn Sekunden, sortiert die Einträge nach dem neuesten Zeitstempel und visualisiert die letzten Aktionen mit lokalisierten Typen sowie farbcodierten Status-Badges. Für leere Feeds oder Fehlerfälle erscheinen Toast-Benachrichtigungen, sodass Operatorinnen laufende Sync-, Such- und Download-Aktivitäten ohne manuelle API-Abfragen im Blick behalten.

### Artists-Verwaltung

Die Artists-Seite im Frontend nutzt die Spotify-Endpunkte `GET /spotify/artists/followed` und `GET /spotify/artist/{artist_id}/releases`, um eine sortierbare Liste der gefolgten Artists inklusive Coverbildern anzuzeigen. In der Detailspalte lassen sich die verfügbaren Releases mit Jahr, Typ und Track-Anzahl inspizieren. Über einen Toggle "Für Sync aktivieren" kann pro Release gesteuert werden, ob der AutoSync-Worker ihn berücksichtigen soll. Änderungen werden gesammelt über `POST /settings/artist-preferences` gespeichert. Lade- und Fehlerzustände werden mit Spinnern, leeren States ("Keine Artists gefunden", "Keine Releases verfügbar") sowie Toasts visualisiert.

## Spotify (`/spotify`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `GET` | `/spotify/status` | Prüft, ob der Spotify-Client authentifiziert ist. |
| `GET` | `/spotify/artists/followed` | Listet alle vom Benutzer gefolgten Artists. |
| `GET` | `/spotify/artist/{artist_id}/releases` | Liefert Alben, Singles und Compilations eines Artists. |
| `GET` | `/spotify/search/tracks?query=...` | Sucht nach Tracks (weitere Endpunkte für Artists/Albums identisch). |
| `GET` | `/spotify/track/{track_id}` | Liefert Track-Details. |
| `GET` | `/spotify/audio-features/{track_id}` | Einzelne Audio-Features. |
| `GET` | `/spotify/audio-features?ids=ID1,ID2` | Mehrere Audio-Features in einem Request. |
| `GET` | `/spotify/playlists` | Listet persistierte Playlists aus der Datenbank. |
| `GET` | `/spotify/playlists/{playlist_id}/tracks` | Holt Playlist-Items (optional `limit`). |
| `POST` | `/spotify/playlists/{playlist_id}/tracks` | Fügt Tracks per URIs hinzu. |
| `DELETE` | `/spotify/playlists/{playlist_id}/tracks` | Entfernt Tracks anhand von URIs. |
| `PUT` | `/spotify/playlists/{playlist_id}/reorder` | Sortiert Playlist neu. |
| `GET` | `/spotify/me` | Gibt das Spotify-Benutzerprofil zurück. |
| `GET` | `/spotify/me/tracks` | Listet gespeicherte Tracks (`limit`). |
| `PUT`/`DELETE` | `/spotify/me/tracks` | Speichert bzw. entfernt gespeicherte Tracks (Payload: `{"ids": [...]}`). |
| `GET` | `/spotify/me/top/{type}` | Top-Tracks oder Artists. |
| `GET` | `/spotify/recommendations` | Empfehlungen anhand Seed-Parametern. |

**Beispiel:**

```http
GET /spotify/search/tracks?query=daft%20punk HTTP/1.1
Authorization: Bearer <token>
```

```json
{
  "items": [
    {
      "id": "2cGxRwrMyEAp8dEbuZaVv6",
      "name": "Harder, Better, Faster, Stronger",
      "artists": [{"name": "Daft Punk"}],
      "album": {"name": "Discovery"}
    }
  ]
}
```

## Plex (`/plex`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `GET` | `/plex/status` | Liefert Sitzungen und Bibliotheksstatistiken. |
| `GET` | `/plex/library/sections` | Listet Bibliotheken (Alias: `/plex/libraries`). |
| `GET` | `/plex/library/sections/{section_id}/all` | Durchsucht eine Bibliothek (Alias: `/plex/library/{section_id}/items`). |
| `GET` | `/plex/library/metadata/{item_id}` | Metadaten für ein Item. |
| `GET` | `/plex/status/sessions` | Aktive Sessions (Alias: `/plex/sessions`). |
| `GET` | `/plex/status/sessions/history/all` | Wiedergabeverlauf (Alias: `/plex/history`). |
| `GET`/`POST` | `/plex/timeline` | Holt bzw. aktualisiert Timeline-Daten. |
| `POST` | `/plex/scrobble` / `/plex/unscrobble` | Spielposition melden. |
| `GET`/`POST`/`PUT`/`DELETE` | `/plex/playlists` | Playlist-Verwaltung. |
| `POST` | `/plex/playQueues` | Erstellt PlayQueues. |
| `GET` | `/plex/playQueues/{playqueue_id}` | Lädt eine bestehende PlayQueue. |
| `POST` | `/plex/rate` | Bewertet ein Item. |
| `POST` | `/plex/tags/{item_id}` | Synchronisiert Tags. |
| `GET` | `/plex/devices` | Verfügbare Geräte. |
| `GET` | `/plex/dvr` | DVR-Daten. |
| `GET` | `/plex/livetv` | Live-TV-Informationen. |
| `GET` | `/plex/notifications` | Server-Sent Events Stream für Plex-Benachrichtigungen. |

**Beispiel:**

```http
GET /plex/library/sections/1/all?type=10 HTTP/1.1
X-Plex-Token: <token>
```

```json
{
  "MediaContainer": {
    "Metadata": [
      {"ratingKey": "123", "title": "Discovery", "parentTitle": "Daft Punk"}
    ]
  }
}
```

## Soulseek (`/soulseek`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `GET` | `/soulseek/status` | Prüft die Verbindung zum slskd-Daemon. |
| `POST` | `/soulseek/search` | Führt eine Suche aus (`{"query": "artist"}`). |
| `POST` | `/soulseek/download` | Persistiert Downloads und stößt Worker an. |
| `GET` | `/soulseek/downloads` | Liefert gespeicherte Downloads aus der DB. |
| `GET` | `/soulseek/download/{id}` | Holt Detailinformationen direkt vom Client. |
| `DELETE` | `/soulseek/download/{id}` | Bricht einen Download ab. |
| `GET` | `/soulseek/downloads/all` | Delegiert an `SoulseekClient.get_all_downloads()`. |
| `DELETE` | `/soulseek/downloads/completed` | Entfernt erledigte Downloads. |
| `GET` | `/soulseek/download/{id}/queue` | Fragt Queue-Positionen ab. |
| `POST` | `/soulseek/enqueue` | Fügt mehrere Dateien der Warteschlange hinzu. |
| `GET` | `/soulseek/uploads` | Lädt Uploads. |
| `GET` | `/soulseek/uploads/all` | Alle Uploads. |
| `DELETE` | `/soulseek/upload/{id}` | Bricht einen Upload ab. |
| `DELETE` | `/soulseek/uploads/completed` | Entfernt erledigte Uploads. |
| `GET` | `/soulseek/user/{username}/address` | IP/Port eines Benutzers. |
| `GET` | `/soulseek/user/{username}/browse` | Lädt die Verzeichnisstruktur. |
| `GET` | `/soulseek/user/{username}/directory?path=...` | Abfrage eines Unterordners. |
| `GET` | `/soulseek/user/{username}/info` | Benutzerinformationen. |
| `GET` | `/soulseek/user/{username}/status` | Online-Status. |

**Beispiel:**

```http
POST /soulseek/download HTTP/1.1
Content-Type: application/json

{
  "username": "dj_user",
  "files": [
    {"filename": "Daft Punk - Harder.mp3", "size": 5120000}
  ]
}
```

```json
{
  "status": "queued",
  "detail": {
    "downloads": [
      {"id": 1, "filename": "Daft Punk - Harder.mp3", "state": "queued", "progress": 0.0}
    ]
  }
}
```

## Matching (`/matching`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `POST` | `/matching/spotify-to-plex` | Matcht einen Spotify-Track gegen Plex-Kandidaten und speichert das Ergebnis. |
| `POST` | `/matching/spotify-to-soulseek` | Bewertet Spotify vs. Soulseek-Kandidaten. |
| `POST` | `/matching/spotify-to-plex-album` | Liefert das beste Album-Match. |

**Beispiel:**

```http
POST /matching/spotify-to-plex HTTP/1.1
Content-Type: application/json

{
  "spotify_track": {"id": "2cGxRwrMyEAp8dEbuZaVv6", "name": "Harder, Better, Faster, Stronger"},
  "candidates": [
    {"id": "123", "title": "Harder Better Faster Stronger", "album": "Discovery"}
  ]
}
```

```json
{
  "best_match": {"id": "123", "title": "Harder Better Faster Stronger", "album": "Discovery"},
  "confidence": 0.98
}
```

## Settings (`/settings`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `GET` | `/settings` | Liefert alle Settings als Key-Value-Map inklusive `updated_at`. |
| `POST` | `/settings` | Legt/aktualisiert einen Eintrag (`{"key": "plex_artist_count", "value": "123"}`). |
| `GET` | `/settings/history` | Zeigt die letzten 50 Änderungen mit Zeitstempel. |
| `GET` | `/settings/artist-preferences` | Gibt die markierten Releases pro Artist zurück. |
| `POST` | `/settings/artist-preferences` | Persistiert die Auswahl (`{"preferences": [{"artist_id": ..., "release_id": ..., "selected": true}]}`). |

**Neue Worker-relevante Settings:**

- `sync_worker_concurrency` – Anzahl paralleler SyncWorker-Tasks (ENV: `SYNC_WORKER_CONCURRENCY`).
- `matching_worker_batch_size` & `matching_confidence_threshold` – Batch-Größe und Confidence-Grenze für den MatchingWorker (ENV: `MATCHING_WORKER_BATCH_SIZE`, `MATCHING_CONFIDENCE_THRESHOLD`).
- `scan_worker_interval_seconds` & `scan_worker_incremental` – Polling-Intervall und Inkrementalscan für den ScanWorker (ENV: `SCAN_WORKER_INTERVAL_SECONDS`, `SCAN_WORKER_INCREMENTAL`).
- `autosync_min_bitrate` & `autosync_preferred_formats` – Qualitätsregeln für Soulseek-Downloads (ENV: `AUTOSYNC_MIN_BITRATE`, `AUTOSYNC_PREFERRED_FORMATS`).
- `metrics.*` und `worker.*` – werden automatisch durch die Worker gepflegt (Herzschläge, Laufzeiten, Erfolgszähler). Sie dienen zur Auswertung durch Monitoring/Prometheus.

## Beets (`/beets`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `POST` | `/beets/import` | Führt `beet import` aus (Payload: `{"path": "/music"}`). |
| `POST` | `/beets/update` | Aktualisiert Metadaten (`beet update`). |
| `POST` | `/beets/remove` | Entfernt Items nach Query (`{"query": "artist:Daft Punk"}`). |
| `POST` | `/beets/move` | Verschiebt Dateien (optional Query). |
| `POST` | `/beets/write` | Schreibt Tags auf Basis einer Query. |
| `GET` | `/beets/albums` | Listet Albumtitel. |
| `GET` | `/beets/tracks` | Listet Tracks. |
| `GET` | `/beets/stats` | Gibt Statistiken (`beet stats`). |
| `GET` | `/beets/fields` | Zeigt verfügbare Feldnamen. |
| `POST` | `/beets/query` | Führt eine Query mit Format-String aus. |

**Beispiel:**

```http
POST /beets/query HTTP/1.1
Content-Type: application/json

{
  "query": "artist:Daft Punk",
  "format": "$artist - $album - $title"
}
```

```json
{
  "results": [
    "Daft Punk - Discovery - Harder, Better, Faster, Stronger"
  ]
}
```
