# Background Workers – Defaults & Konfiguration

Harmony betreibt mehrere asynchrone Worker, die beim Lifespan-Start der FastAPI-Anwendung initialisiert werden. Dieses Dokument liefert einen konsolidierten Überblick über Aufgaben, Standardwerte, relevante Umgebungsvariablen sowie praktische Beispielprofile.

## Überblick

| Worker | Modul | Aufgabe |
| --- | --- | --- |
| `SyncWorker` | `app/workers/sync_worker.py` | Lädt Dateien über Soulseek herunter, führt Nachbearbeitung durch und aktualisiert Retry-Informationen. |
| `MatchingWorker` | `app/workers/matching_worker.py` | Persistiert neue Match-Ergebnisse und verarbeitet die `WorkerJob`-Queue. |
| `PlaylistSyncWorker` | `app/workers/playlist_sync_worker.py` | Synchronisiert gespeicherte Spotify-Playlists mit der Datenbank. |
| `ArtworkWorker` | `app/workers/artwork_worker.py` | Lädt Cover in hoher Auflösung, cached Dateien und bettet sie in Downloads ein. |
| `LyricsWorker` | `app/workers/lyrics_worker.py` | Erstellt `.lrc`-Dateien aus Spotify-Lyrics bzw. externen Quellen. |
| `MetadataWorker` | `app/workers/metadata_worker.py` | Ergänzt Metadaten wie Genres, Komponist:innen oder ISRC-Codes. |
| `BackfillWorker` | `app/workers/backfill_worker.py` | Reichert FREE-Ingest-Daten mit Spotify-Informationen an. |
| `WatchlistWorker` | `app/workers/watchlist_worker.py` | Überwacht Artists auf neue Releases und stößt automatische Downloads an. |
| `RetryScheduler` | `app/workers/retry_scheduler.py` | Plant fehlgeschlagene Downloads mit Backoff neu ein. |

## Lebenszyklus & Steuerung

- Die Worker werden beim Aufruf von `app.router.lifespan_context(app)` gestartet und beim Shutdown kontrolliert gestoppt.
- `HARMONY_DISABLE_WORKERS=1` deaktiviert sämtliche Hintergrund-Worker – praktisch für Read-only-Demos oder Tests.
- Einzelne Worker können über Feature-Flags deaktiviert werden (`ENABLE_ARTWORK`, `ENABLE_LYRICS`).
- Beim Start emittiert die Anwendung ein strukturiertes Log-Event `worker.config` mit den wichtigsten Parametern (`component="bootstrap"`, `status="ok"`). Das Event enthält ausschließlich nicht-sensible Metadaten und erleichtert das Monitoring der aktiven Defaults.

## ENV-Variablen & Defaults

### Watchlist & Scheduling

| Variable | Default | Wirkung | Hinweise |
| --- | ---: | --- | --- |
| `WATCHLIST_INTERVAL` | `86400` | Wartezeit in Sekunden zwischen zwei vollständigen Watchlist-Runs. | Für lokale Tests auf `300–900` reduzieren. |
| `WATCHLIST_MAX_CONCURRENCY`<br>`WATCHLIST_CONCURRENCY` | `3` | Parallele Artists pro Tick. | Alias `WATCHLIST_CONCURRENCY` wird weiterhin akzeptiert. |
| `WATCHLIST_MAX_PER_TICK` | `20` | Anzahl der Artists pro Tick. | Höhere Werte erhöhen API-Last. |
| `WATCHLIST_BACKOFF_BASE_MS` | `250` | Basiswert für exponentielles Retry-Backoff. | Kombiniert mit `WATCHLIST_JITTER_PCT`. |
| `WATCHLIST_JITTER_PCT` | `0.2` | Zufälliger Jitter (±20 %) für Backoff-Verzögerungen. | Werte >1.0 werden auf Prozentbasis interpretiert. |
| `WATCHLIST_RETRY_BUDGET_PER_ARTIST` | `6` | Maximale Retries pro Artist bevor ein Cooldown greift. | Cooldown-Minuten über `WATCHLIST_COOLDOWN_MINUTES`. |
| `WATCHLIST_RETRY_MAX` | `3` | Retries pro Tick bevor Jobs in die DLQ verschoben werden. | | 

### Queue, Retry & DLQ

| Variable | Default | Wirkung | Hinweise |
| --- | ---: | --- | --- |
| `WORKER_VISIBILITY_TIMEOUT_S` | `60` | Lease-Dauer für persistente Worker-Jobs. | Minimum sind 5 s; längere Jobs entsprechend erhöhen. |
| `RETRY_MAX_ATTEMPTS` | `10` | Automatische Neuversuche pro Download. | Gilt für Sync/RetryScheduler. |
| `RETRY_BASE_SECONDS` | `60` | Basiswartezeit zwischen Retries. | Wird exponentiell mit `RETRY_JITTER_PCT` kombiniert. |
| `RETRY_JITTER_PCT` | `0.2` | Zufallsanteil (±20 %) für Retry-Verzögerungen. | |
| `DLQ_PAGE_SIZE_DEFAULT` | `25` | Standardpaginierung für DLQ-Listen. | Anpassbar bis `DLQ_PAGE_SIZE_MAX`. |
| `DLQ_REQUEUE_LIMIT` | `500` | Obergrenze für Bulk-Requeue. | |
| `DLQ_PURGE_LIMIT` | `1000` | Obergrenze für Bulk-Purge. | |

### Provider & Externe Abhängigkeiten

| Variable | Default | Wirkung | Hinweise |
| --- | ---: | --- | --- |
| `PROVIDER_MAX_CONCURRENCY` | `4` | Maximale Parallelität für Integrationen. | Sollte zu Provider-Limits passen. |
| `SLSKD_TIMEOUT_MS` | `8000` | Timeout (ms) für Soulseek-Requests. | Bei instabilen Netzen erhöhen. |
| `SLSKD_RETRY_MAX` | `3` | Retries für Soulseek-Anfragen. | | 
| `SLSKD_RETRY_BACKOFF_BASE_MS` | `250` | Basis-Delay für Soulseek-Retries. | |
| `SLSKD_JITTER_PCT` | `20.0` | Zufallsjitter (±20 %) für Soulseek-Retries. | |

### Feature-Flags & globale Schalter

| Variable | Default | Wirkung | Hinweise |
| --- | ---: | --- | --- |
| `HARMONY_DISABLE_WORKERS` | `0` | Globaler Kill-Switch für alle Worker. | `1` deaktiviert sämtliche Hintergrundprozesse. |
| `ENABLE_ARTWORK` | `0` | Aktiviert Artwork-Worker und API-Endpunkte. | | 
| `ENABLE_LYRICS` | `0` | Aktiviert Lyrics-Worker und API-Endpunkte. | |
| `FEATURE_REQUIRE_AUTH` | `0` | Erzwingt API-Key-Authentifizierung. | Hat Einfluss auf Worker, die externe APIs ansteuern. |
| `FEATURE_RATE_LIMITING` | `0` | Aktiviert requestbasierte Rate-Limits. | Relevant für Worker-APIs, die über das Gateway laufen. |

## Beispiel-Profile

### Development (`.env`)

```bash
HARMONY_DISABLE_WORKERS=0
WATCHLIST_INTERVAL=600
WATCHLIST_MAX_CONCURRENCY=2
WATCHLIST_BACKOFF_BASE_MS=250
WATCHLIST_JITTER_PCT=0.2
WORKER_VISIBILITY_TIMEOUT_S=45
PROVIDER_MAX_CONCURRENCY=3
SLSKD_TIMEOUT_MS=10000
SLSKD_RETRY_MAX=2
SLSKD_RETRY_BACKOFF_BASE_MS=250
SLSKD_JITTER_PCT=15.0
FEATURE_REQUIRE_AUTH=false
FEATURE_RATE_LIMITING=false
```

### Production (`.env`)

```bash
HARMONY_DISABLE_WORKERS=0
WATCHLIST_INTERVAL=86400
WATCHLIST_MAX_CONCURRENCY=3
WATCHLIST_BACKOFF_BASE_MS=250
WATCHLIST_JITTER_PCT=0.2
WORKER_VISIBILITY_TIMEOUT_S=60
PROVIDER_MAX_CONCURRENCY=4
SLSKD_TIMEOUT_MS=8000
SLSKD_RETRY_MAX=3
SLSKD_RETRY_BACKOFF_BASE_MS=250
SLSKD_JITTER_PCT=20.0
FEATURE_REQUIRE_AUTH=true
FEATURE_RATE_LIMITING=true
```

## Troubleshooting

- **Worker starten nicht:** Prüfen, ob `HARMONY_DISABLE_WORKERS=1` gesetzt ist oder Feature-Flags einzelne Worker blockieren.
- **Watchlist-Läufe dauern zu lange:** `WATCHLIST_INTERVAL`, `WATCHLIST_MAX_CONCURRENCY` und `WATCHLIST_MAX_PER_TICK` an API-Limits und Datenvolumen anpassen.
- **Jobs bleiben in der Queue hängen:** `WORKER_VISIBILITY_TIMEOUT_S` für langlaufende Aufgaben erhöhen und DLQ via `/dlq`-Endpoints prüfen.
- **Soulseek-Timeouts:** `SLSKD_TIMEOUT_MS` und `SLSKD_RETRY_MAX` schrittweise erhöhen; Backoff-Werte zur Schonung des Providers nutzen.
- **Rate-Limit-Fehler über Gateway:** `FEATURE_RATE_LIMITING` deaktivieren oder Limits in der Gateway-Konfiguration anpassen.

## Weiterführende Ressourcen

- [`README.md`](../README.md) – vollständige ENV-Referenz inklusive Frontend-Variablen.
- [`docs/ops/runtime-config.md`](ops/runtime-config.md) – Laufzeitkonfiguration & Prioritätenmatrix.
- [`reports/analysis/config_matrix.md`](../reports/analysis/config_matrix.md) – Detailanalyse der Konfigurationsquellen.
