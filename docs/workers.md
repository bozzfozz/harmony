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

## Lebenszyklus & Steuerung

- Die Worker werden beim Aufruf von `app.router.lifespan_context(app)` gestartet und beim Shutdown kontrolliert gestoppt.
- `HARMONY_DISABLE_WORKERS=1` deaktiviert sämtliche Hintergrund-Worker – praktisch für Read-only-Demos oder Tests.
- Einzelne Worker können über Feature-Flags deaktiviert werden (`ENABLE_ARTWORK`, `ENABLE_LYRICS`).
- Beim Start emittiert die Anwendung ein strukturiertes Log-Event `worker.config` mit den wichtigsten Parametern (`component="bootstrap"`, `status="ok"`). Das Event enthält ausschließlich nicht-sensible Metadaten und erleichtert das Monitoring der aktiven Defaults.

### Orchestrator-Komponenten

Harmony betreibt einen Orchestrator, der das Starten und Stoppen der Worker kapselt und die folgenden Teile orchestriert:

- **Scheduler (`app/orchestrator/scheduler.py`)** – Liest aktivierte Jobs aus der Konfiguration, erzeugt Worker-Aufgaben und startet sie im Hintergrund. Der Scheduler läuft als wiederverwendbarer Task, kann vor dem eigentlichen Start ein Stop-Signal entgegennehmen und setzt interne Status-Flags (`started`, `stopped`, `stop_requested`).
- **Dispatcher (`app/orchestrator/dispatcher.py`)** – Verteilt `WorkerJob`-Einträge an die passenden Handler. Er wird bei Lifespan-Start zusammen mit dem Scheduler erstellt, respektiert Stop-Signale und wartet beim Shutdown auf laufende Dispatch-Loops.
- **WatchlistTimer (`app/orchestrator/timer.py`)** – Startet periodische Watchlist-Läufe. Der Timer nutzt dieselbe Start/Stopp-Semantik wie Scheduler und Dispatcher, damit keine Ticks während des Shutdowns mehr ausgeführt werden.

Der Scheduler plant orchestrierte Jobs (`sync`, `matching`, `retry`, `watchlist`) und sorgt dafür, dass fehlgeschlagene Downloads ausschließlich über den `retry`-Job erneut eingeplant werden. Damit entfällt die frühere dedizierte Retry-Schleife aus dem Archiv vollständig.

Die Komponenten werden aus `app/orchestrator/bootstrap.py` heraus initialisiert. Der dort definierte `WORKERS_ENABLED`-Schalter entscheidet zur Laufzeit, ob der Orchestrator überhaupt gestartet wird. Dadurch können API-Instanzen ohne Hintergrundprozesse betrieben werden, ohne an anderer Stelle Code ändern zu müssen.

#### Prioritäten & Pools

- Prioritäten können JSON-basiert (`ORCH_PRIORITY_JSON`) oder als CSV (`ORCH_PRIORITY_CSV`) konfiguriert werden. Höhere Zahlen bedeuten bevorzugte Abholung im Scheduler.
- Der Dispatcher respektiert `ORCH_GLOBAL_CONCURRENCY` sowie optionale `ORCH_POOL_<JOB>` Limits (z. B. `ORCH_POOL_SYNC=3`). Pools fallen ohne eigenen Wert auf das globale Limit zurück.
- Der Scheduler pollt in Abständen von `ORCH_POLL_INTERVAL_MS` Millisekunden. Werte kleiner als 10 ms werden automatisch auf 10 ms angehoben, Werte ≤0 deaktivieren das Schlafen.

#### Sichtbarkeit & Heartbeats

- `ORCH_VISIBILITY_TIMEOUT_S` definiert das Lease beim Leasing der Jobs, während `WORKER_VISIBILITY_TIMEOUT_S` weiterhin als Fallback beim Enqueue dient. Beide Werte sollten deckungsgleich sein, damit Heartbeats und Redelivery vorhersehbar bleiben.
- Während der Job-Verarbeitung sendet der Dispatcher alle `lease_timeout_seconds * 0.5` Sekunden einen Heartbeat. Schlägt die Verlängerung fehl, wird ein `event=orchestrator.heartbeat` mit `status="lost"` protokolliert und der Job wird zur Sicherheit neu verteilt.
- Handler können eine eigene `visibility_timeout` im Payload setzen, falls ein Job bewusst länger laufen darf. Der orchestratorische Timeout wirkt dann als Obergrenze.

## ENV-Variablen & Defaults

> **Single Source:** `get_app_config().environment.workers` spiegelt `WATCHLIST_INTERVAL`, `WORKER_VISIBILITY_TIMEOUT_S`, `WATCHLIST_TIMER_ENABLED` und den Kill-Switch `HARMONY_DISABLE_WORKERS`. Worker-Code sollte diese Werte nicht mehr direkt via `os.getenv()` lesen.

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
| `RETRY_MAX_ATTEMPTS` | `10` | Automatische Neuversuche pro Download. | Gilt für Sync-Handler und orchestrierte Retry-Flows. |
| `RETRY_BASE_SECONDS` | `60` | Basiswartezeit zwischen Retries. | Wird exponentiell mit `RETRY_JITTER_PCT` kombiniert. |
| `RETRY_JITTER_PCT` | `0.2` | Zufallsanteil (±20 %) für Retry-Verzögerungen. | |
| `DLQ_PAGE_SIZE_DEFAULT` | `25` | Standardpaginierung für DLQ-Listen. | Anpassbar bis `DLQ_PAGE_SIZE_MAX`. |
| `DLQ_REQUEUE_LIMIT` | `500` | Obergrenze für Bulk-Requeue. | |
| `DLQ_PURGE_LIMIT` | `1000` | Obergrenze für Bulk-Purge. | |

### Provider & Externe Abhängigkeiten

| Variable | Default | Wirkung | Hinweise |
| --- | ---: | --- | --- |
| `PROVIDER_MAX_CONCURRENCY` | `4` | Maximale Parallelität für Integrationen. | Sollte zu Provider-Limits passen. |
| `SLSKD_TIMEOUT_MS` | `8_000` | Timeout (ms) für Soulseek-Requests. | Bei instabilen Netzen erhöhen. |
| `SLSKD_TIMEOUT_SEC` | `300` | Timeout (s) für den HDM-Soulseek-Client. | Überschreibt den aus `SLSKD_TIMEOUT_MS` abgeleiteten Wert. |
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
SLSKD_TIMEOUT_SEC=120
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
SLSKD_TIMEOUT_SEC=180
SLSKD_TIMEOUT_MS=8_000
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
- **Soulseek-Timeouts:** `SLSKD_TIMEOUT_SEC` (HDM) bzw. `SLSKD_TIMEOUT_MS` und `SLSKD_RETRY_MAX` schrittweise erhöhen; Backoff-Werte zur Schonung des Providers nutzen.
- **Rate-Limit-Fehler über Gateway:** `FEATURE_RATE_LIMITING` deaktivieren oder Limits in der Gateway-Konfiguration anpassen.

## Weiterführende Ressourcen

- [`README.md`](../README.md) – vollständige ENV-Referenz inklusive Frontend-Variablen.
- [`docs/ops/runtime-config.md`](ops/runtime-config.md) – Laufzeitkonfiguration & Prioritätenmatrix.
- [`reports/analysis/config_matrix.md`](../reports/analysis/config_matrix.md) – Detailanalyse der Konfigurationsquellen.
