# Health Endpoints

Harmony exposes two built-in health routes that surface the container status and
upstream dependency checks.

## `/live`

- **Purpose:** Simple liveness probe. Returns HTTP 200 with `{ "status": "ok" }` once
  the application server has started.
- **Dependencies:** None. The handler does not touch the database or external
  integrations.
- **Usage:** Suitable for container orchestrator liveness probes or manual smoke tests:
  `curl -fsS http://127.0.0.1:8080/live`.

## `/api/health/ready`

- **Purpose:** Readiness probe exposing a JSON document with the overall status and
  optional dependency details.
- **Default behaviour:**
  - Checks SQLite availability (unless `HEALTH_READY_REQUIRE_DB=false`).
  - Executes configured dependency probes listed via the `HEALTH_DEPS` environment
    variable (e.g. `spotify`, `slskd`).
  - Reports aggregated status in the `status` field (`ok`, `degraded`, `down`).
- **Verbose mode:** Append `?verbose=1` to include per-check timing, error messages and
  dependency outcomes.
- **Example:**

  ```bash
  curl -fsS "http://127.0.0.1:8080/api/health/ready?verbose=1"
  ```

- **Exit signals:** A non-200 response indicates the container should not receive
  traffic yet. Check structured logs (`health.ready`) for the failing dependency.

## Self-check CLI

For pre-deployment verification you can run the built-in guard locally:

```bash
python -m app.ops.selfcheck --assert-startup
```

The command validates environment variables, volume permissions and dependency reach.
It exits with non-zero codes for misconfiguration and mirrors the readiness logic.
