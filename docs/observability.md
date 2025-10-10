# Observability

Harmony exposes lightweight endpoints for infrastructure health checks and relies on structured logs for runtime observability.

## Health

### `GET /api/v1/health`
- **Purpose:** Liveness probe without external I/O.
- **Response:**
  ```json
  {
    "ok": true,
    "data": {
      "status": "up",
      "version": "1.4.0",
      "uptime_s": 123.4
    },
    "error": null
  }
  ```
- **Notes:** Returns instantly and reports the process uptime and application version.

### `GET /api/v1/ready`
- **Purpose:** Readiness probe checking the database connection and configured downstream integrations.
- **Success Response:**
  ```json
  {
    "ok": true,
    "data": {
      "db": "up",
      "deps": {
        "spotify": "up"
      }
    },
    "error": null
  }
  ```
- **Failure Response (`503 Service Unavailable`):**
  ```json
  {
    "ok": false,
    "error": {
      "code": "DEPENDENCY_ERROR",
      "message": "not ready",
      "meta": {
        "db": "down",
        "deps": {
          "spotify": "down"
        }
      }
    }
  }
  ```
- **Alias:** `GET /api/health/ready` liefert für Infrastruktur-Checks ein reduziertes `{ "status": "ok" }` bzw. `503` im Fehlerfall.
- **Behaviour:** Database checks honour `HEALTH_DB_TIMEOUT_MS`. Dependency checks run in parallel with the timeout configured by `HEALTH_DEP_TIMEOUT_MS`. When `HEALTH_READY_REQUIRE_DB=false` the database state is still reported but does not gate readiness.

### `GET /api/v1/metrics`
- **Purpose:** Prometheus scrape endpoint exposing Harmony runtime metrics.
- **Response:** Plain text in the Prometheus exposition format with `Content-Type: text/plain; version=0.0.4`.
- **Caching:** Responses set `Cache-Control: no-store` so scrapers always fetch fresh samples.
- **Highlights:**
  - `hdm_item_outcomes_total{state="…"}` – terminal outcome counts for orchestrated downloads (`done`, `failed`, `duplicate`).
  - `hdm_item_retries_total{error_type="…"}` – retry attempts by error class.
  - `hdm_item_failures_total{error_type="…"}` – fatal failures grouped by exception type.
  - `hdm_phase_duration_seconds{phase="download|tagging|moving"}` – phase-level histograms useful for latency breakdowns.
  - `hdm_processing_seconds` – total per-item processing latency histogram.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `HEALTH_DB_TIMEOUT_MS` | `500` | Timeout for the database readiness probe. |
| `HEALTH_DEP_TIMEOUT_MS` | `800` | Timeout for each dependency readiness probe. |
| `HEALTH_DEPS` | _(empty)_ | Comma-separated list of dependency identifiers to probe. |
| `HEALTH_READY_REQUIRE_DB` | `true` | Require a healthy database for readiness. |

## Logging Signals

Structured logging is standardised via `app.logging_events.log_event` across the stack. Key event types:

- `api.request` – emitted by the FastAPI middleware for every request. Fields include `component`, `method`, `path`, `status_code`, `status`, `duration_ms`, and the `entity_id`/request id. Router-specific emitters (z. B. `router.search`) forward to `app.logging_events.log_event`, sodass Monkeypatches und Telemetrie-Shims in Tests greifen.
- `api.dependency` – wraps outbound provider calls with `dependency`, `operation`, `status`, retry counters, `duration_ms`, and optional error metadata (`timeout_ms`, `status_code`, `retry_after_ms`).
- `cache.*` – `cache.store`, `cache.hit`, `cache.miss`, `cache.expired`, `cache.invalidate`, `cache.evict` capture cache lifecycle actions with hashes instead of payloads.
- `worker.job` – queue persistence lifecycle for `enqueued`, `leased`, `completed`, `dead_letter`, and `priority_updated` states. Includes `entity_id`, `job_type`, `attempts`, and context such as `lease_timeout_s` or `stop_reason`.
- `worker.retry_exhausted` – emitted when retries are exhausted and the job moves to the DLQ.
- `worker.tick` – periodic queue polling output with `job_type` and `count` of ready jobs.
- `orchestrator.schedule|lease|dispatch|commit|heartbeat|dlq|timer_tick` – high level orchestration flow and timing, including `duration_ms`, `status`, and job identifiers. Diese Ereignisse werden über den Logger `app.orchestrator.metrics` ausgegeben, damit Dashboards konsistent auf den Metrik-Stream subscriben können.
- `worker.playlists.cache.invalidate` – dokumentiert Cache-Busts der Playlist-Synchronisation inklusive `invalidated_entries`, `playlist_count` sowie `meta.playlist_ids` für gezielte Analysen.

A typical log record looks like:

```json
{
  "event": "api.request",
  "component": "api",
  "method": "GET",
  "path": "/api/v1/health",
  "status": "ok",
  "status_code": 200,
  "duration_ms": 2.14,
  "entity_id": "6a3f2d40-bd5d-4cb0-b089-75d6f8ebf2c1"
}
```

Forward these logs to your aggregation stack (Loki, ELK, etc.) to build dashboards and alerts using the structured fields.
