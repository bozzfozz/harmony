# Logging- & Observability-Vertrag

## Ziele
- Einheitliches `event`-Feld je Log-Eintrag für einfache Filterbarkeit (Elastic, Loki).  
- Pflichtfelder: `event`, `component`, `status`, `duration_ms` (falls messbar), `entity_id` (Request-, Job- oder Artist-ID), `meta` (optionales Dict).  
- Levels: `INFO` für Erfolg/Status, `WARNING` für Recoverable Errors, `ERROR` für harte Fehler.  

## Aktueller Status
- Response-Cache nutzt strukturierte `extra`-Payloads (`event=cache.hit/miss/...`).【F:app/services/cache.py†L70-L135】  
- Search-API nutzt den `log_event`-Helper (über `_emit_api_event`) und übergibt strukturierte Felder für `api.request`-Events, während Logger-Errors für Totalausfälle bestehen bleiben.【F:app/api/search.py†L103-L180】
- Watchlist-Worker emittiert Lifecycle- und Ergebnis-Events über `log_event` statt manuell serialisierter Strings, z. B. für `worker.start`, `worker.stop` und Tick-Ergebnisse.【F:app/workers/watchlist_worker.py†L52-L195】
→ Ergebnis: Uneinheitliche JSON-Keys, erschwerte Aggregation.

## Vorschlag für kanonische Events

| Event | Kategorie | Pflichtfelder | Beschreibung / Trigger |
| --- | --- | --- | --- |
| `api.request` | API | `component=router.<name>`, `status`, `duration_ms`, `path`, `method`, `request_id` | Jeder Endpoint nach Response-Generierung. |
| `api.dependency` | API | `component`, `status`, `dependency`, `duration_ms`, `meta.retry_after_ms?` | Aufrufe externer Dienste (Spotify, slskd). |
| `cache.hit` / `cache.miss` / `cache.store` | Infrastruktur | `component=cache`, `key_hash`, `path`, `status`, `ttl_s` | Bestehende Events fortführen, Key kürzen. |
| `worker.tick` | Worker | `component=worker.<name>`, `status`, `duration_ms`, `jobs_total`, `jobs_success`, `jobs_failed` | Jeder Durchlauf einer Worker-Hauptschleife. |
| `worker.job` | Worker | `component=worker.<name>`, `entity_id=job_id`, `status`, `attempt`, `duration_ms`, `meta.reason` | Job-bezogene Events (enqueue, success, failure). |
| `worker.retry_exhausted` | Worker | `component`, `entity_id`, `status="failed"`, `attempts`, `meta.last_error` | Wenn Retry-Budget aufgebraucht. |
| `integration.health` | Integrationen | `component=integration.<provider>`, `status`, `meta.details` | Wird von Health-Check/Registry emittiert. |

## Feld-Schema
```
{
  "event": "api.request",
  "component": "router.search",
  "status": "ok",
  "duration_ms": 142.5,
  "entity_id": "req-<uuid>",
  "path": "/api/v1/search",
  "method": "POST",
  "meta": {
    "sources": ["spotify", "soulseek"],
    "partial_failures": []
  }
}
```

## Implementierungsleitfaden
1. **Helper bereitstellen:** `app.logging_events.log_event(logger, event, **fields)` erzeugt strukturiertes Dict (`extra={"event": …, **fields}`).  
2. **Router-Middleware:** Request/Response-Zeit messen und `api.request` emitten (nutzt `time.perf_counter`).  
3. **Dependency-Aufrufe:** Wrapper in `app/services/integration_service` und `SoulseekClient` implementieren, der vor/nach API-Calls `api.dependency` loggt.【F:app/services/integration_service.py†L31-L86】  
4. **Worker-Basis:** Gemeinsames Mixin (z. B. `LoggingWorkerMixin`) stellt `emit_event(name, **fields)` bereit; bestehende `logger.info("event=watchlist...")` ersetzen.【F:app/workers/watchlist_worker.py†L93-L103】  
5. **Queue-Interaktionen:** `PersistentJobQueue.enqueue/mark_running/mark_done` sollen `worker.job`-Events emittieren (inkl. Idempotenz-Flag).【F:app/workers/persistence.py†L50-L147】  
6. **Metrics-Anbindung:** Optional Prometheus-Counter/Histogram (z. B. `search_requests_total`, `worker_jobs_latency_seconds`) auf Basis derselben Events, um doppelte Arbeit zu vermeiden.

## Beispiel-Events (Soll)
- **Cache Treffer:**
  ```python
  log_event(logger, "cache.hit", component="cache", key_hash=entry.key[:12], path=entry.path_template, ttl_s=ttl_value)
  ```
- **Search API Erfolg:**
  ```python
  start = time.perf_counter()
  ...
  log_event(
      logger,
      "api.request",
      component="router.search",
      status="ok",
      duration_ms=(time.perf_counter() - start) * 1000,
      entity_id=request.headers.get("X-Request-ID"),
      path=request.url.path,
      method=request.method,
      meta={"sources": resolved_sources, "partial_failures": sorted(failures.keys())},
  )
  ```
- **Worker Retry Exhausted:**
  ```python
  log_event(
      logger,
      "worker.retry_exhausted",
      component="worker.watchlist",
      entity_id=str(artist.spotify_artist_id),
      status="failed",
      attempts=state.attempts,
      meta={"reason": failure.status}
  )
  ```

## Rollout-Strategie
1. Helper + Tests hinzufügen.  
2. Response-Cache auf Helper migrieren (keine Logikänderung).  
3. Search-Router, IntegrationService, Watchlist-Worker iterativ umstellen.  
4. Dashboard/Alerting (Grafana/Kibana) auf neue Events umkonfigurieren.  
5. Alte string-basierte Logs entfernen, sobald Dashboards aktualisiert sind.

