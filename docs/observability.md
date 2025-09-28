# Observability Endpoints

Harmony exposes lightweight endpoints for infrastructure health checks and Prometheus compatible metrics.

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

## Metrics

### `GET /metrics`
- **Purpose:** Expose Prometheus-compatible metrics (`text/plain; version=0.0.4`).
- **Default Metrics:**
  - `app_build_info{version="<semver>"}` gauge.
  - `app_requests_total{method="<verb>",path="<route>",status="<code>"}` counter.
  - `app_request_duration_seconds_*` histogram with SLO-friendly buckets.
- **Feature Flag:** Controlled by `FEATURE_METRICS_ENABLED`. When disabled the endpoint responds with `404 Not Found` and is hidden from OpenAPI.
- **Authentication:** Obeys `METRICS_REQUIRE_API_KEY`. If disabled, add the configured metrics path to the API-key allowlist or rely on the automatic allowlist update in `app.config`.

### Metrics Examples
```
# HELP app_build_info Build information for the Harmony backend
# TYPE app_build_info gauge
app_build_info{version="1.4.0"} 1
# HELP app_requests_total Total number of processed HTTP requests
# TYPE app_requests_total counter
app_requests_total{method="GET",path="/api/v1/health",status="200"} 3
# HELP app_request_duration_seconds Request duration in seconds
# TYPE app_request_duration_seconds histogram
app_request_duration_seconds_bucket{method="GET",path="/api/v1/health",status="200",le="0.01"} 3
...
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `HEALTH_DB_TIMEOUT_MS` | `500` | Timeout for the database readiness probe. |
| `HEALTH_DEP_TIMEOUT_MS` | `800` | Timeout for each dependency readiness probe. |
| `HEALTH_DEPS` | _(empty)_ | Comma-separated list of dependency identifiers to probe. |
| `HEALTH_READY_REQUIRE_DB` | `true` | Require a healthy database for readiness. |
| `FEATURE_METRICS_ENABLED` | `false` | Toggle the `/metrics` endpoint. |
| `METRICS_PATH` | `/metrics` | Path where metrics are exposed. |
| `METRICS_REQUIRE_API_KEY` | `true` | Require global API-key authentication for metrics. |

## Logging Signals

The following structured log events support monitoring:

- `event=health.check` &rarr; emitted for the liveness endpoint with `status` and `duration_ms`.
- `event=ready.check` &rarr; emitted for the readiness endpoint with `db`, `deps_up`, `deps_down`, and `duration_ms`.
- `event=metrics.expose` &rarr; emitted whenever `/metrics` is requested with `enabled` state.

These logs allow exporting health data to external log-based alerting systems when Prometheus is unavailable.
