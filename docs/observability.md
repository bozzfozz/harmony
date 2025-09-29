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
- **Behaviour:** Database checks honour `HEALTH_DB_TIMEOUT_MS`. Dependency checks run in parallel with the timeout configured by `HEALTH_DEP_TIMEOUT_MS`. When `HEALTH_READY_REQUIRE_DB=false` the database state is still reported but does not gate readiness.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `HEALTH_DB_TIMEOUT_MS` | `500` | Timeout for the database readiness probe. |
| `HEALTH_DEP_TIMEOUT_MS` | `800` | Timeout for each dependency readiness probe. |
| `HEALTH_DEPS` | _(empty)_ | Comma-separated list of dependency identifiers to probe. |
| `HEALTH_READY_REQUIRE_DB` | `true` | Require a healthy database for readiness. |

## Logging Signals

The following structured log events support monitoring and replace classic Prometheus scrapes:

- `event=request` &rarr; includes `route`, `status`, `duration_ms` and optionally `cache_status` for every HTTP request.
- `event=worker_job` &rarr; includes `job_id`, `attempt`, `status`, and `duration_ms` for background workers.
- `event=integration_call` &rarr; includes `provider`, `status`, and `duration_ms` for outbound API calls.
- `event=health.check` and `event=ready.check` &rarr; include probe specific metadata (`status`, `deps_up`, `deps_down`, `duration_ms`).

Forward these logs to your aggregation stack (Loki, ELK, etc.) and build dashboards/alerts based on the structured fields.
