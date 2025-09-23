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
| `POST` | `/api/sync` | Startet einen manuellen Playlist- und Bibliotheksabgleich. |
| `POST` | `/api/search` | Führt eine Quell-übergreifende Suche (Spotify/Plex/Soulseek) aus. |
| `POST` | `/api/download` | Persistiert Downloads und übergibt sie an den Soulseek-Worker. |
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

**Download-Beispiel:**

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
    {"id": 42, "filename": "Daft Punk - Harder.mp3", "state": "queued", "progress": 0.0}
  ]
}
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

Die neue Downloads-Seite im Harmony-Frontend ermöglicht das Starten von Test-Downloads über eine beliebige Datei- oder Track-ID und zeigt aktive Transfers inklusive Status und Fortschrittsbalken an. Über Tailwind- und shadcn/ui-Komponenten werden Ladezustände, Leerlaufmeldungen sowie Fehler-Toasts konsistent dargestellt. Jeder erfolgreich gestartete Download löst eine Bestätigungsmeldung aus, während fehlgeschlagene Anfragen klar hervorgehoben werden.

![Activity-Feed-Widget](activity-feed-widget.svg)

Auf dem Dashboard ergänzt das Activity-Feed-Widget die bestehenden Statuskacheln. Es pollt den `/api/activity`-Endpunkt alle zehn Sekunden, visualisiert die letzten Aktionen mit Zeitstempel, Typ und Status-Badge und informiert per Toast, falls der Feed leer bleibt oder das Backend nicht erreichbar ist. Dadurch behalten Operatorinnen laufende Sync-, Such- und Download-Aktivitäten im Blick, ohne das Backend manuell abfragen zu müssen.

## Spotify (`/spotify`)

| Methode | Pfad | Beschreibung |
| --- | --- | --- |
| `GET` | `/spotify/status` | Prüft, ob der Spotify-Client authentifiziert ist. |
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
