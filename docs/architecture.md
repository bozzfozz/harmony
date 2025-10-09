# Architekturübersicht

Die MVP-Slim-Version von Harmony fokussiert sich auf Spotify und Soulseek. Ehemalige Plex-Module wurden entfernt und werden zur Laufzeit nicht geladen. Der aktive Codepfad besteht aus folgenden Bausteinen:

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
| SQLAlchemy + PostgreSQL    |
+----------------------------+
```

Harmony betreibt sämtliche Persistenz ausschließlich auf PostgreSQL. Die
Konfiguration erzwingt `postgresql+psycopg://` oder `postgresql+asyncpg://`
Verbindungszeichenketten; ein eingebetteter oder file-basierter Fallback wird
nicht initialisiert.
Das frühere file-basierte Smoke-Setup bleibt lediglich als Diagnosewerkzeug im
Archiv und besitzt keine Parität zu den produktiven Pfaden.

## Komponenten im Detail

### Core

- **SpotifyClient** (`app/core/spotify_client.py`): kapselt OAuth, Suche, Audio-Features, Playlists und Nutzerinformationen.
- **SoulseekClient** (`app/core/soulseek_client.py`): kommuniziert mit slskd (Downloads, Uploads, Userinfos, Warteschlangen).
- **MusicMatchingEngine** (`app/core/matching_engine.py`): berechnet Scores für Spotify↔Soulseek-Kandidaten.
- **Utilities** (`app/utils/*`): Normalisierung, Metadaten, Activity-Logging, Service-Health.

### Routers

FastAPI-Router kapseln die öffentliche API und werden in `app/main.py` registriert. Aktiv sind u. a.:

- [`app/api/spotify.py`](../app/api/spotify.py): bündelt die Spotify-Domain und stellt `router`, `core_router`, `backfill_router`, `free_router` und `free_ingest_router` für Suche, Moduswechsel, Backfill sowie FREE-Import-Flows bereit.
- [`app/api/search.py`](../app/api/search.py): aggregiert Suchanfragen über Spotify und Soulseek inklusive Score-Normalisierung und Event-Logging.
- [`app/api/system.py`](../app/api/system.py): liefert Health-/Readiness-Endpunkte, Secret-Validierung und Worker-Monitoring für das Dashboard.
- [`app/api/routers/watchlist.py`](../app/api/routers/watchlist.py): verwaltet die Watchlist-API (CRUD auf `/watchlist`).
- [`app/api/router_registry.py`](../app/api/router_registry.py): führt die Domains zusammen, registriert Soulseek-, Matching-, Metadata-, Settings-, Activity- und Download-Router und kapselt Legacy-Namespace-Weiterleitungen.

Hinweis: Die verbleibenden Module unter `app/routers/` dienen nur noch als Kompatibilitäts-Shims und re-exportieren die eigentlichen Router aus `app/api/…`.

#### Soulseek UI Dashboard

- Die Frontend-Ansicht **„Soulseek“** bündelt vier Kernbereiche für Operator:innen:
  - **Verbindung & Integrationen:** nutzt `/soulseek/status` und `/integrations`, um den Connectivity-Status sowie Provider-Health inklusive Detailhinweisen (z. B. fehlende Credentials) anzuzeigen.
  - **Konfigurationsübersicht:** lädt die relevanten `SLSKD_*`-Einstellungen über `/settings`, maskiert Secrets und markiert fehlende Pflichtwerte (Basis-URL/API-Key) deutlich.
  - **Aktive Uploads:** ruft `/soulseek/uploads` bzw. `/soulseek/uploads/all` ab, stellt Fortschritt, Benutzer:innen, Größe und Durchsatz als Tabelle dar und signalisiert Fehlerzustände mit Retry-Möglichkeit.
  - **Download-Überwachung:** bindet `/soulseek/downloads` und `/soulseek/downloads/all` ein, zeigt Priorität, Retry-Zähler und letzte Fehler pro Transfer und erlaubt den Wechsel zwischen aktiven und historischen Downloads.
- **Interpretation der Hinweise:**
  - Das Badge **„Verbunden“** bestätigt, dass der Backend-Proxy (`slskd`) erreichbar ist. **„Getrennt“** bedeutet, dass Downloads/Uploads blockiert sind und Worker in Folge mit Retries starten.
  - Der Abschnitt **„Provider-Gesundheit“** spiegelt die `/integrations`-Bewertung wider. `degraded` deutet auf optionale, aber relevante Warnungen hin (z. B. fehlende Bandbreitenlimits), `down` auf harte Ausfälle oder fehlende Credentials. Detailfelder listen die Rohwerte aus dem Health-Endpunkt.
  - In der Konfiguration kennzeichnet ein rotes Badge fehlende Pflichtwerte. Maskierte Secrets erscheinen als `••••••`; Operator:innen können so prüfen, ob Werte grundsätzlich gesetzt sind, ohne sie offenzulegen.
  - Die Upload-Tabelle zeigt jeden aktiven Share mit Status, Fortschritt, Transfergröße und Geschwindigkeit. Bei leerem Ergebnis informiert der Hinweis „Aktuell sind keine Uploads aktiv“, Fehlerzustände liefern einen Retry-Button, der erneut `/soulseek/uploads` aufruft.
  - Die Download-Tabelle aggregiert Daten aus persistenter Datenbank und Live-Queue, inklusive Priorität, Retry-Historie und Zeitstempeln. Über die Umschalter „Alle Downloads anzeigen“/„Nur aktive Downloads“ lassen sich Altlasten prüfen; der Retry-Button stößt eine erneute Synchronisation der Liste an, sodass Operator:innen nach manuellen Requeues den Zustand kontrollieren können.
- Die Seite dient als Operations-Dashboard für den Soulseek-Daemon: Warnhinweise bei Ausfällen oder fehlender Konfiguration helfen, bevor Sync-Worker oder Upload-Freigaben ins Stocken geraten.
- **Navigation-Warnhinweise:** Die linke Seitenleiste übernimmt die gleichen Integrationssignale. Ein gelbes Badge „Eingeschränkt“ weist auf degradierte Dienste hin (z. B. wenn `/integrations` `degraded` meldet), rote Badges „Offline“ bzw. „Fehler“ kennzeichnen fehlende Konfiguration oder nicht erreichbare Services. Tooltips und Screenreader-Texte wiederholen die Warnung – auch im eingeklappten Zustand der Navigation – damit Operator:innen die Soulseek- und Matching-Dashboards gezielt aufrufen können.

#### Matching UI Dashboard

- Die Ansicht **„Matching“** ergänzt das Operations-Cockpit um den `MatchingWorker` und die Score-Qualität der gespeicherten Zuordnungen.
  - Der Kartenbereich **„Worker-Status“** zeigt Heartbeat, Queue-Größe und Status-Badge des Matching-Workers. Ein gelbes Banner weist bei `stale`/`blocked`-Zuständen auf ausstehende Heartbeats oder blockierte Jobs hin, ein rotes Banner markiert `stopped`/`errored`-Zustände mit Handlungsempfehlung (Worker neu starten, Logs prüfen).
  - Sobald `queue_size > 0` gemeldet wird, erscheint ein zusätzlicher Hinweis mit dem Backlog-Wert, damit Operator:innen den Dispatcher oder die Matching-Konfiguration überprüfen können.
- **Matching-Metriken** berechnen die zuletzt gespeicherte Durchschnitts-Konfidenz sowie kumulierte `saved_total`/`discarded_total`-Zähler.
  - Hohe Werte (> 85 %) werden grün hervorgehoben, niedrige Scores (< 45 %) lösen eine rote Markierung aus. So lässt sich erkennen, ob die Matching-Konfiguration (z. B. Schwellenwerte) angepasst werden muss.
  - Der Wert **„Verworfen in letzter Charge“** signalisiert, ob eine Charge komplett verworfen wurde und liefert damit einen direkten Trigger zur Ursachenanalyse (fehlende Kandidaten, falsche Thresholds).
- Der Abschnitt **„Letzte Matching-Batches“** zieht die Activity-Logs (`type=metadata`, `status=matching_batch`).
  - Jede Charge zeigt gespeicherte und verworfene Kandidaten sowie die durchschnittliche Konfidenz. Wenn alles verworfen wurde, erscheint ein rotes Badge „Alles verworfen“ und der Eintrag wandert an die Spitze der Ereignisliste.
  - Die Timeline hilft beim Correlieren von Fehlerspitzen mit Konfigurationsänderungen oder Worker-Ausfällen; bei Bedarf lassen sich Queue- und Score-Hinweise direkt daneben ablesen.

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

Fehlgeschlagene Downloads werden ausschließlich über den orchestrierten `retry`-Job verarbeitet, der den gleichen Backoff wie der Sync-Worker verwendet und keine dedizierte Worker-Schleife mehr benötigt. Der frühere Scan-/AutoSync-Stack liegt vollständig im Archiv und wird im Systemstatus nicht mehr angezeigt.

### Datenbank & Persistenz

- **`app/db.py`** initialisiert die PostgreSQL-Engine (synchron und asynchron) und liefert `session_scope()` / `get_session()`. Die Initialisierung lehnt andere Backends ab; ohne gültigen PostgreSQL-DSN startet der Lifespan nicht.
- **`app/models.py`** definiert Tabellen wie `Playlist`, `Download`, `Match`, `Setting`, `SettingHistory`, `WatchlistArtist`.
- **`app/schemas.py` & `app/schemas_search.py`** beschreiben Pydantic-Modelle für Requests/Responses und Suchresultate.
- Alembic-Migrationen laufen beim Start (`init_db()`) ausschließlich gegen PostgreSQL. Fällt Alembic als Abhängigkeit weg, ruft der Fallback `Base.metadata.create_all()` dieselbe Engine auf und setzt ebenfalls PostgreSQL voraus.

### Datenfluss (vereinfacht)

1. **Ingest**: Spotify-Free-Uploads und API-Aufrufe landen als `ingest_jobs`/`ingest_items` in der Datenbank.
2. **Backfill**: Der Backfill-Worker reichert FREE-Daten mit Spotify-IDs, ISRC, Laufzeiten und Playlist-Expansion an.
3. **Soulseek Matching & Downloads**: MatchingWorker bewertet Kandidaten, SyncWorker lädt Dateien und aktualisiert Status.
4. **Postprocessing**: Artwork-, Lyrics- und Metadata-Worker ergänzen Metadaten und Artefakte; Datei-Organisation läuft im SyncWorker.
5. **Watchlist & Activity**: WatchlistWorker triggert neue Downloads, `activity_manager` zeichnet Events für UI/Automatisierungen auf.

### Observability & Wiring Guard

- Beim Start protokolliert `app/main.py` ein `wiring_summary` mit aktiven Routern, Workern und Integrationen (deaktivierte Provider erscheinen mit `False`).
- `scripts/audit_wiring.py` stellt sicher, dass keine Legacy-Integrations-Referenzen (z. B. Plex) außerhalb des Archivs in `app/` oder `tests/` landen und ist in der CI eingebunden.

### Archivierte Module

Legacy-Code (Plex-Router, Scan-Worker, AutoSync) wurde entfernt. Die aktiven Tests (`tests/test_matching.py`) verifizieren, dass entsprechende Endpunkte `404` liefern.
