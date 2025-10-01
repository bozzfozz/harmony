# Architecture Contracts

Dieses Dokument präzisiert die verbindlichen Verträge für Logging, Fehler, DTOs, Idempotenz, Retries und Dead-Letter-Queues. Die Verträge gelten für API-Router, Services, Core, Integrationen und Worker gleichermaßen und werden im Rahmen jedes PR-Reviews überprüft.

## Structured Logging Contract

### Pflichtfelder
| Feld | Typ | Beschreibung |
| --- | --- | --- |
| `event` | `str` | Event-Kategorie (siehe Tabelle unten). |
| `component` | `str` | Modul oder technische Komponente (`router.spotify`, `service.watchlist`, `worker.ingest`). |
| `status` | `str` | `received`, `in_progress`, `completed`, `failed`, `skipped`, `timeout`. |
| `duration_ms` | `int` | Dauer in Millisekunden (0 wenn unbekannt). |
| `entity_id` | `str` | Domänen- oder Job-Identifikator (`track:123`, `job:watchlist:42`). |
| `request_id` | `str` | Korrelations-ID (API Request oder Job Lease). |
| `meta` | `dict[str, Any]` | Zusätzliche strukturierte Informationen (Flags, Retry-Count, Provider, HTTP-Status). |

### Event-Typen
| `event` | Auslöser | Pflicht-Meta |
| --- | --- | --- |
| `request` | Eingang/Antwort eines HTTP-Requests. | `method`, `path`, `status_code`. |
| `service.call` | Aufruf einer Service-Methode. | `service`, `operation`. |
| `integration_call` | ProviderGateway ruft externen Provider auf. | `provider`, `operation`, `attempt`, `timeout_ms`. |
| `worker_job` | Worker startet/beendet Job. | `job_type`, `attempt`, `queue`. |
| `worker.heartbeat` | Lease-Heartbeat vom Handler. | `job_type`, `lease_id`, `visibility_timeout_ms`. |
| `orchestrator.scheduler` | Scheduler holt/vergibt Leases. | `queue`, `priority`, `leased_count`. |
| `dlq.transition` | Job geht in/aus DLQ. | `job_type`, `reason`. |
| `feature_flag` | Feature-Flag Evaluierung. | `flag`, `value`, `source`. |

Logs müssen JSON-formatiert sein und alle Pflichtfelder enthalten. Fehler-Events setzen `status=failed` und referenzieren die Fehlertaxonomie (`meta.error_code`).

## Fehler-Taxonomie

| Code | Beschreibung | HTTP-Mapping | Logging-Kriterien |
| --- | --- | --- | --- |
| `VALIDATION_ERROR` | Eingaben verletzen Schema, Pflichtfelder oder Grenzen. | `400` | `meta.fields`, `meta.detail` beschreiben Validierungsfehler. |
| `NOT_FOUND` | Angefragte Ressource existiert nicht oder ist nicht verfügbar. | `404` | `meta.resource` und ggf. `meta.provider` ergänzen Kontext. |
| `DEPENDENCY_ERROR` | Fehler in externen Diensten oder Integrationen (inkl. Zeitüberschreitungen). | `502` oder `504` | `meta.provider`, `meta.dependency_status`, `meta.retryable` verpflichtend. |
| `INTERNAL_ERROR` | Unbekannter Fehler, ungehandelte Exceptions. | `500` | `meta.exception_type`, `meta.retryable=false`. |

Alle Router wandeln Exceptions in einen Fehler-Envelope (`{"ok": false, "error": {"code", "message", "meta"}}`). Services signalisieren wiederholbare Fehler durch `meta.retryable=true`.

## ProviderGateway DTO-Kontrakte

### ProviderRequest
| Feld | Typ | Beschreibung |
| --- | --- | --- |
| `operation` | `Literal["search", "download", "status", "metadata"]` | Gateway-Operation. |
| `payload` | `dict[str, Any]` | Normalisierter Input (Artists, Titel, Album, Query-Parameter). |
| `context` | `dict[str, Any]` | Aufrufkontext (`request_id`, `idempotency_key`, Feature-Flags). |
| `timeout_ms` | `int` | Zeitlimit pro Provider-Aufruf. |

### ProviderResponse
| Feld | Typ | Beschreibung |
| --- | --- | --- |
| `status` | `Literal["ok", "partial", "error"]` | Ergebnisstatus. |
| `data` | `Union[dict[str, Any], list[dict[str, Any]], None]` | Ergebnisdaten (Tracks, Download-IDs, Health). |
| `error` | `Optional[dict[str, Any]]` | Enthält `code` (Taxonomie), `message`, `provider_status`. |
| `meta` | `dict[str, Any]` | Retry-/Rate-Limit-Hinweise, Quoten, Cache-Hits. |

### Track DTO (Normalform)
| Feld | Beschreibung |
| --- | --- |
| `track_id` | Provider-interne ID oder Harmony-ID. |
| `title` | Normalisierter Track-Titel. |
| `artists` | Liste normalisierter Künstlernamen. |
| `album` | Albumtitel in Normalform. |
| `duration_ms` | Dauer in Millisekunden. |
| `isrc` | Optional, wenn verfügbar. |
| `bitrate` | Für Downloads relevant (Soulseek). |

Gateway-Adapter müssen DTOs vor Rückgabe validieren, fehlende Pflichtfelder führen zu `VALIDATION_ERROR`.

## Idempotenz, Visibility & Heartbeats
- **API-Requests:** Header `Idempotency-Key` wird in Persistence (z. B. `ingest_jobs.idempotency_key`) gespeichert. Schlüssel-Format: `<domain>:<entity-id>:<epoch-ms>`. Kollisionen führen zu `409` mit bestehender Response.
- **Queue-Jobs:** Jeder Job enthält `idempotency_key` (gleiche Struktur). Services prüfen vor Enqueue auf bestehende Jobs (persistierte `job_keys`).
- **Visibility Timeout:** Default 30 s, konfigurierbar per `WORKER_VISIBILITY_TIMEOUT_MS`. Heartbeats spätestens bei 2/3 der Sichtbarkeitsdauer. Ausbleibende Heartbeats lösen Requeue mit erhöhtem `attempt` aus.
- **Lease-Erneuerung:** Handler, die länger laufen, senden `worker.heartbeat`-Events mit aktualisiertem `visibility_timeout_ms`.
- **DLQ:** Nach Ausschöpfen von `WORKER_MAX_ATTEMPTS` landet der Job in `dlq_jobs`. Jeder Übergang erzeugt `event=dlq.transition` mit `status=entered` oder `status=requeued`.

## Retry- und Backoff-Regeln
- **Exponentiell mit Jitter:** `next_retry_at = now + base * 2^(attempt-1) ± 20%` (Deckel laut Konfiguration, z. B. 5 s bei Watchlist).
- **Retry-Budgets:** Konfigurierbar pro Job-Typ (`WATCHLIST_RETRY_MAX`, `INGEST_RETRY_MAX`). Budgetverletzung setzt `meta.retryable=false`.
- **Dependency Errors:** Provider-Adapter kennzeichnen `DEPENDENCY_ERROR` als wiederholbar, solange Quoten/Rate-Limits dies erlauben (`meta.retry_after_ms`).
- **Manual DLQ Requeue:** `/api/v1/dlq` nutzt denselben Contract und setzt neue Lease + `idempotency_key`.

## Visibility & Feature Flags
- Feature-Flags werden im Service-Layer ausgewertet; Router dürfen Flags nur lesen.
- Jede Flag-Änderung erzeugt `event=feature_flag` mit `status=updated`.
- Flags mit Laufzeitauswirkung müssen im Runtime-Config-Guide und in der Architekturübersicht referenziert werden.

Diese Verträge sind Grundlage für Tests und Reviews. Änderungen müssen per ADR dokumentiert, in `overview.md` und relevanten Guides nachgezogen und in der PR-Checkliste erwähnt werden.
