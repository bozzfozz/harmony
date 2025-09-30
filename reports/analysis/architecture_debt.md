# Architektur-Schuldenanalyse – Harmony Backend & Schnittstellen

## Executive Summary
- Die API-Schicht umfasst 17 Router, die in `app/main.py` direkt zusammengebaut werden und stellenweise Datenbank- und Worker-Instanzen selbst verwalten, was zu enger Kopplung und redundanten Initialisierungspfaden führt.【F:app/main.py†L178-L323】【F:app/routers/spotify_router.py†L160-L209】【F:app/routers/backfill_router.py†L24-L80】
- Hintergrundprozesse werden im FastAPI-Lebenszyklus aufgebaut; die Geschäftslogik für Watchlist-, Backfill- und Sync-Worker hängt an `app.state` und erschwert Testbarkeit, Idempotenz und das Abschalten einzelner Worker.【F:app/main.py†L239-L352】【F:app/workers/persistence.py†L50-L191】【F:app/workers/watchlist_worker.py†L61-L118】
- Die Such- und Matching-Pipeline verzahnt Router, Integrations-Service, Matching-Engine und Library-Service eng miteinander; Konfigurationsgrenzen (Timeouts, Kandidatenlimits) sind mehrfach verteilt.【F:app/routers/search_router.py†L76-L176】【F:app/services/integration_service.py†L31-L86】【F:app/core/matching_engine.py†L74-L209】【F:app/services/library_service.py†L45-L126】
- Logging- und Observability-Pattern divergieren: Einige Komponenten liefern strukturierte `extra`-Felder, andere formatieren Schlüssel/Werte im Nachrichtentext, wodurch Korrelation und Metrik-Auswertung erschwert wird.【F:app/services/cache.py†L70-L135】【F:app/workers/watchlist_worker.py†L93-L103】【F:app/routers/search_router.py†L127-L154】

## Detailanalyse der Haupt-Schulden

### 1. Router- und Service-Sprawl
**Beobachtung.** `app/main.py` importiert und registriert 17 Router einzeln. Router wie `spotify_router` greifen direkt auf DB-Sessions oder `SpotifyClient` zu, ohne einen Zwischenservice zu nutzen. `backfill_router` baut Worker-Instanzen innerhalb der Request-Handler auf und cached sie in `app.state`.

**Evidenz.**
- Router-Registrierung & Tagging: `app/main.py` Zeilen 178–200.【F:app/main.py†L178-L201】
- Direktzugriff auf SQLAlchemy-Session im Router: `app/routers/spotify_router.py` Zeilen 160–162.【F:app/routers/spotify_router.py†L160-L162】
- Worker-Erzeugung im Request: `app/routers/backfill_router.py` Zeilen 24–80.【F:app/routers/backfill_router.py†L24-L80】

**Auswirkungen.**
- Harte Kopplung zwischen API und Infrastruktur (DB/Worker) erschwert das Stubben in Tests und die spätere Extraktion in Microservices.
- Mehrfach-Initialisierung (z. B. Backfill Worker) droht bei parallelen Requests zu Race Conditions.
- Fehlende Bündelung der Spotify-Domäne (Router `spotify`, `spotify/free`, `backfill`, `free_ingest`) erhöht Duplikate.

**Schuldenklasse.** Struktur-/Layer-Verletzung, mittleres Risiko.

### 2. Worker-Orchestrierung innerhalb des Web-Lifecycles
**Beobachtung.** `_start_background_workers` instanziiert neun Worker, speichert sie als Attribute von `app.state` und verlässt sich auf `asyncio`-Lifecycle. Persistente Queue-Operationen (`PersistentJobQueue`) implementieren Leasing- und Idempotenzlogik isoliert.

**Evidenz.**
- Worker-Bootstrap & Statusbericht: `app/main.py` Zeilen 239–323, 374–417.【F:app/main.py†L239-L323】【F:app/main.py†L374-L417】
- Job-Queue-Idempotenz & Visibility-Timeout: `app/workers/persistence.py` Zeilen 50–191.【F:app/workers/persistence.py†L50-L191】
- Watchlist-Worker initialisiert eigene Semaphore, Backoff und Logging-Konventionen: `app/workers/watchlist_worker.py` Zeilen 61–118.【F:app/workers/watchlist_worker.py†L61-L118】

**Auswirkungen.**
- Kein zentraler Orchestrator für Start/Stopp/Health einzelner Worker ⇒ schweres Feature-Toggling.
- Retry-, Visibility-Timeout- und Backoff-Werte pro Worker verstreut; kein globaler DLQ/Backpressure-Plan.
- Risiko: Worker-Neustarts über API verursachen Zustand in `app.state`, nicht persistiert.

**Schuldenklasse.** Betriebsführung / Zuverlässigkeit, mittleres bis hohes Risiko.

### 3. Such- und Matching-Pipeline
**Beobachtung.** `smart_search` erstellt pro Quelle Tasks, orchestriert Timeout-Handling, Score-Normalisierung und Matching. `IntegrationService.search_tracks` unterstützt nur `SlskdAdapter` und kapselt Timeout/Retry eigenständig, obwohl `ProviderRegistry` weitere Adapter baut.

**Evidenz.**
- Parallele Quellenverarbeitung & Logging: `app/routers/search_router.py` Zeilen 76–176.【F:app/routers/search_router.py†L76-L176】
- Provider-spezifisches Timeout/Retry-Handling: `app/services/integration_service.py` Zeilen 31–86.【F:app/services/integration_service.py†L31-L86】
- Matching-Engine & Library-Service mit konfigurativen Schwellenwerten: `app/core/matching_engine.py` Zeilen 74–209; `app/services/library_service.py` Zeilen 45–126.【F:app/core/matching_engine.py†L74-L209】【F:app/services/library_service.py†L45-L126】

**Auswirkungen.**
- Limitiert Erweiterbarkeit auf weitere Provider (Plex/Spotify) – Sonderlogik blockiert generische Nutzung.
- Schwellenwerte (Artist Similarity, Candidate Limits) liegen in mehreren Schichten ⇒ hoher kognitiver Aufwand für Tuning.
- Kein zentraler Retry-/Backoff-Wrapper für externe Dienste ⇒ ungleichmäßige Fehlerbehandlung.

**Schuldenklasse.** Domänenlogik & Integrationsschicht, hohes Verbesserungspotenzial.

### 4. Uneinheitliche Observability
**Beobachtung.** Response-Cache schreibt strukturierte Events via `extra`, Search- und Worker-Komponenten kodieren Felder im Nachrichtentext. Dadurch fehlen konsistente Schlüssel (`event`, `duration_ms`, `entity_id`).

**Evidenz.**
- Strukturierte Cache-Events: `app/services/cache.py` Zeilen 70–135.【F:app/services/cache.py†L70-L135】
- Watchlist-Worker formatiert Logtext manuell: `app/workers/watchlist_worker.py` Zeilen 93–103.【F:app/workers/watchlist_worker.py†L93-L103】
- Search-Router Logging mischt strukturierte und unstrukturierte Felder: `app/routers/search_router.py` Zeilen 127–154.【F:app/routers/search_router.py†L127-L154】

**Auswirkungen.**
- Querying/Alerting via ELK o. Ä. erschwert; keine durchgängige `event`-Taxonomie.
- Fehlende Korrelation (z. B. `request_id` / `job_id`) verhindert Ursachenanalyse.

**Schuldenklasse.** Observability, mittleres Risiko.

## Sequenzdiagramme

### Ist-Zustand (vereinfachte Track-Suche & Matching)
```
Client
  │
  ▼
FastAPI Router (smart_search)
  │  async tasks
  ├────────────► SpotifyClient.search_* (Threadpool)
  │               │
  │               ▼
  │            Spotify API
  │
  ├────────────► SoulseekClient.search
  │               │
  │               ▼
  │             slskd API
  │
  ▼
_scoring & filtering_ (matching_engine + normalize utils)
  │
  ▼
Response assembly
```

### Soll-Variante A – Entkoppelte Gateway-Schicht
```
Client
  │
  ▼
API Controller (SearchService)
  │
  ▼
ProviderGateway (async orchestration)
  │           ├──> ProviderAdapter (Spotify)
  │           ├──> ProviderAdapter (slskd)
  │           └──> ProviderAdapter (Plex,…)
  ▼
RankingService (MatchingEngine + config)
  │
  ▼
DTO Mapper → Response
```
**Trade-offs:** + Einfache Provider-Erweiterung, + zentrale Timeout/Retry-Regeln; − erfordert Refactoring mehrerer Router, − zusätzliche Abstraktionsschicht.

### Soll-Variante B – Worker-Orchestrator
```
FastAPI lifespan
  │
  ▼
WorkerOrchestrator.start()
  │          ├──> WorkerRegistry (config-driven)
  │          └──> HealthReporter/DLQ
  ▼
AppState hält nur Handles
```
**Trade-offs:** + Klare Start/Stopp-API, + Tests isolierbar; − Umbau der bestehenden `app.state`-Nutzung, − ggf. Migrationsaufwand für Admin-Endpunkte.

## Weitere Beobachtungen
- Frontend `frontend/src/lib/api.ts` dupliziert Endpoint-Pfade, die Backend-Basis `/api/v1` erst zur Laufzeit erhält; spätere Konsolidierung mit generiertem Client empfohlen.【F:frontend/src/lib/api.ts†L1-L610】【F:app/main.py†L178-L201】
- `MatchingWorker` und `SyncWorker` beziehen Retry/Backoff-Werte aus ENV (`MATCHING_WORKER_BATCH_SIZE`, `RETRY_*`); eine zentrale Konfigurationsmatrix (s. separate Datei) reduziert Fehlkonfiguration.

