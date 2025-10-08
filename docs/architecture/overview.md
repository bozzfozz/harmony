# Harmony Architecture Overview

Diese Übersicht definiert den gemeinsamen Bezugsrahmen für Router, Services, Core-Domain und Orchestrator. Sie stellt Prinzipien, Flows und Verträge bereit, die bei jeder Änderung geprüft werden müssen. Ergänzende Details finden sich in `docs/architecture/contracts.md`, `docs/architecture/diagrams.md` sowie den ADRs unter `docs/architecture/adr/`.

## Zweck & Leitprinzipien

- **Simplicity First:** Kleine, klar abgegrenzte Komponenten, die ohne versteckte Kopplungen funktionieren.
- **Idempotenz als Standard:** Jede Anfrage und jeder Job darf gefahrlos erneut laufen (Queue-Redelivery, API-Retries, Deployments).
- **DRY & KISS:** Fachlogik liegt im Core bzw. dedizierten Services; Router und Integrationen bleiben dünne Adapter.
- **Least-Privilege:** Integrationen nutzen nur die benötigten Scopes, Worker erhalten minimale Rechte auf Queues und Provider.
- **Strukturiertes Logging:** Jede Entscheidung erzeugt nachvollziehbare, schemakonforme Events (siehe Contracts-Dokument).

## Schichtenmodell

| Schicht                    | Verantwortung                                                                      | Beispielmodule                                         | Anti-Patterns                                                 |
| -------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------- |
| **API (Router)**           | HTTP-/CLI-Oberfläche, Request-Validierung, Fehler-Envelope, Auth.                  | `app/api/*`, `app/api/routers/*`, FastAPI Dependencies | Business-Logik, Direktzugriff auf Datenbank oder Provider     |
| **Application (Services)** | Orchestriert Use-Cases, kapselt Transaktionen, orchestriert mehrere Integrationen. | `app/services/*`, `app/workers/*`                      | Zustandsbehaftete globale Variablen, direkte Response-Objekte |
| **Domain (Core)**          | Reine Fachlogik, Matching, Normalisierung, Fehlerklassen.                          | `app/core/*`, `app/errors.py`                          | Provider-spezifische DTOs, Side-Effects                       |
| **Infrastructure**         | Integrationen, Persistence, Messaging, Konfiguration.                              | `app/integrations/*`, `app/db.py`, `app/models.py`     | Domain-Logik in Adapter verschieben                           |
| **Orchestrator/Workers**   | Zeit-/Event-gesteuerte Jobs, Dispatch, Visibility-Handling, Heartbeats.            | `app/workers/*`, `app/services/dlq_service.py`         | API-Calls ohne Idempotenz, ungeplante Retries                 |

## Modulverantwortungen

| Modul/Komponente                                              | Rolle                                                                              | Owners            | Qualitätskriterien                                                         |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------- |
| Router (`app/api/routers/*`)                                  | Übersetzt HTTP-Requests in Service-Aufrufe, validiert Input und mappt Fehlercodes. | API-Team          | FastAPI-Schemata gepflegt, kein Datenbankzugriff, Logging `event=request`. |
| Services (`app/services/*`)                                   | Enthält Anwendungs-Use-Cases, koordiniert Integrationen und Domain-Komponenten.    | Core-Team         | Idempotente Methoden, Transaktionsgrenzen dokumentiert, Retry-fähig.       |
| Core (`app/core/*`)                                           | Domain-Modelle, Matching, Normalisierung, Fehler.                                  | Domain-Team       | Reine Funktionen, deterministische Tests, keine Provider-Aufrufe.          |
| Integrationen (`app/integrations/*`)                          | Provider-spezifische Adapters, Mapping von DTOs, Timeout/Retries.                  | Integrations-Team | Logging `event=integration_call`, Fehler auf Taxonomie gemappt.            |
| Orchestrator (`app/workers/*`, `app/services/dlq_service.py`) | Job-Planung, Dispatch, Visibility, Dead-Letter-Handling.                           | Platform-Team     | Lease-Verträge eingehalten, Heartbeat-Events, DLQ gepflegt.                |

Der frühere Pfad `app/routers/*` stellt nur noch Legacy-Reexports bereit und darf nicht mehr als Quelle für neue Endpunkte verwendet werden. Beim Import geben diese Module eine `DeprecationWarning` mit dem Zielpfad (`app.api.routers.*`) aus und reichen den aktuellen Router unverändert weiter.

## Kern-Flows

### Request → Response

1. Router validiert Payload, prüft Authentifizierung und erzeugt `event=request` mit `status=received`.
2. Router ruft den passenden Service auf und übergibt normalisierte DTOs (siehe Contracts).
3. Services orchestrieren Core-Logik und Integrationen, loggen `event=service.call` und `event=integration_call` mit Dauer.
4. Fehler werden auf die Taxonomie (`VALIDATION_ERROR`, `NOT_FOUND`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`) gemappt.
5. Router wandelt Domain- oder Service-Resultate in Response-DTOs um und emittiert `event=request` mit `status=completed`.

### Job Lifecycle (Queue)

1. Service oder Timer enqueued einen Job mit Idempotency-Key (`<job-type>:<entity-id>:<timestamp-epoch>`).
2. Orchestrator-Scheduler reserviert Jobs nach Priorität, setzt Visibility Timeout und vergibt eine Lease.
3. Dispatcher übergibt den Job an einen Worker-Pool; Handler bestätigt Heartbeats innerhalb des Visibility-Fensters.
4. Bei Erfolg acked der Handler den Job, loggt `event=worker_job` mit `status=completed`.
5. Bei Fehlern: Retry mit exponentiellem Backoff (Budget aus Config), Überschreitung landet im DLQ (`event=worker_job`, `status=failed`).

### Watchlist Timer → Enqueue → Handler

1. Timer löst gemäß `WATCHLIST_INTERVAL` aus, liest Artists mit fälligem `last_checked`.
2. Service erstellt pro Artist einen `artist_refresh`-Job und setzt Idempotency-Key `artist-refresh:<artist-id>:<tick-start>`.
3. Worker lädt Spotify-Releases, mappt auf Downloads und triggert Soulseek-Enqueue über den ProviderGateway.
4. Erfolgreiche Läufe loggen `event=artist.scan status=ok` und löschen Retry-Cooldowns; Fehler emittieren `event=artist.scan status=retry|failed` und respektieren Budget/Backoff. `ARTIST_MAX_RETRY_PER_ARTIST` und `ARTIST_COOLDOWN_S` überschreiben die Watchlist-Defaults für Budget und Cooldown sekundengenau.
5. Ist `ARTIST_CACHE_INVALIDATE=true`, schreiben die Refresh-/Delta-Handler Cache-Hints (`event=artist.delta`) bzw. räumen Einträge via `cache.evict`; Persistenz-Schritte loggen `event=artist.persist`.

## Fehler-, Retry- und Idempotenzverträge

- **Logging-Contract:** Jedes Event enthält `event`, `component`, `status`, `duration_ms`, `entity_id` (siehe `contracts.md`).
- **Fehlertaxonomie:** Konsistent zu FastAPI/Error-Envelope (`code`, `message`, optional `meta`).
- **Retries:** Services definieren maximale Versuche, Backoff-Strategien und DLQ-Hand-Off; Werte dokumentiert in `docs/architecture/contracts.md`.
- **Idempotenz:** API-Clients übermitteln `Idempotency-Key`-Header; Worker nutzen Queue-Keys und Persistenz, um Doppelverarbeitung zu verhindern.
- **Visibility & Heartbeat:** Jede Lease setzt `visibility_timeout` und fordert Heartbeats (`event=worker.heartbeat`) innerhalb 2/3 der Lease-Dauer.

## Konfiguration & Feature-Flags

- **Konfigurationsmatrix:** `docs/ops/runtime-config.md` listet relevante ENV-Variablen (Ingest, Watchlist, Provider, Orchestrator). Neue Parameter dort und in dieser Übersicht verlinken.
- **Feature-Flags:** `ENABLE_LYRICS`, `ENABLE_ARTWORK`, `ARTIST_CACHE_INVALIDATE`, `INGEST_MAX_PENDING_JOBS`, `WATCHLIST_MAX_CONCURRENCY` u. a. werden in Services geprüft und müssen hier dokumentiert bleiben.
- **Observability:** Structured Logs bleiben primär; ergänzend stehen Prometheus-Metriken für Scan/Refresh (`artist_scan_outcomes_total`, `artist_refresh_duration_seconds` u. a.) zur Verfügung. Externe Systeme abonnieren `event=request`, `event=worker_job`, `event=integration_call`.
- **Caching:** `CACHE_WRITE_THROUGH` sorgt für sofortige Invalidierung der Spotify-Playlist-Routen; `cache.evict`-Events dokumentieren gezielte Räumungen.

## Erweiterungspunkte

- **Neue Provider:** Implementiere `MusicProvider`-Adapter, ergänze Mapping in `ProviderGateway`, schreibe ADR bei signifikanten Schnittstellenänderungen.
- **Neue Job-Typen:** Definiere Worker-Handler inkl. Visibility-, Retry- und DLQ-Strategie, erweitere Orchestrator-Konfiguration und dokumentiere den Flow.
- **Neue APIs:** Router delegieren strikt an bestehende Services oder neue Use-Case-Services; Fehler und Logging folgen dem Contract.

Änderungen an Architektur, Flows oder Verträgen erfordern ein ADR (siehe Template) und eine Aktualisierung dieser Übersicht.
