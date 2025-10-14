# Harmony

Harmony is a FastAPI backend that unifies Spotify metadata, Soulseek downloads and local
post-processing into a single automation-friendly music hub. The unified container
exposes the API on **port 8080** and stores all state in SQLite.

> **Frontend status:** The legacy static bundle has been removed. A new server-side
> rendered UI (FastAPI + Jinja2 + HTMX) is planned under `/ui`; implementation follows the
> published specifications. See [`docs/ui/fe-htmx-plan.md`](docs/ui/fe-htmx-plan.md) for the
> sitemap & HTMX contracts, [`docs/operations/security.md`](docs/operations/security.md) for
> session/role details, and [`docs/ui/csp.md`](docs/ui/csp.md) for CSP guidance. No Node.js
> toolchain is required.

## Highlights

- **Harmony Download Manager (HDM):** Orchestrates watchlists, ingest jobs and
  enrichment workers, writing downloads to `/data/downloads` and promoting verified
  tracks into `/data/music`.
- **Unified Image:** One container delivers API, background workers and UI with a single
  exposed port and health surface.
- **Provider Integrations:** Spotify PRO (OAuth) and FREE flows plus Soulseek (slskd)
  provide matching, downloads and metadata enrichment.

See the extended overview in [`docs/overview.md`](docs/overview.md).
The complete documentation map lives in [`docs/README.md`](docs/README.md).

## Quickstart

### `docker run`

```bash
docker run -d \
  --name harmony \
  -p 8080:8080 \
  -e HARMONY_API_KEYS=change-me \
  -e ALLOWED_ORIGINS=http://localhost:8080 \
  -v $(pwd)/data/downloads:/data/downloads \
  -v $(pwd)/data/music:/data/music \
  ghcr.io/bozzfozz/harmony:latest
```

- The container creates the SQLite database at `/data/harmony.db`.
- Mount `/data/downloads` and `/data/music` to persist downloads and the organised
  library.
- Verify the deployment with `curl -fsS http://127.0.0.1:8080/live` and
  `curl -fsS "http://127.0.0.1:8080/api/health/ready?verbose=1"`.
  The versioned system endpoints live under `/api/v1/...`; see
  [`docs/ui/fe-htmx-plan.md`](docs/ui/fe-htmx-plan.md) for the UI wiring overview.

A compose example with the same defaults lives in
[`docs/install/docker.md`](docs/install/docker.md).

## Minimal configuration

Only a few environment variables are required for a local deployment:

| Variable | Purpose | Example |
| --- | --- | --- |
| `HARMONY_API_KEYS` | Comma-separated API keys accepted by the gateway. | `secret-local-key` |
| `ALLOWED_ORIGINS` | CORS allowlist for the browser UI. | `http://localhost:8080` |
| `DOWNLOADS_DIR` | Workspace for HDM downloads. | `/data/downloads` |
| `MUSIC_DIR` | Target library for organised media. | `/data/music` |

All other knobs are documented in [`docs/configuration.md`](docs/configuration.md).

## Health checks

- `GET /live` → returns `{ "status": "ok" }` without touching external dependencies.
- `GET /api/health/ready` → performs SQLite and integration checks. Use `?verbose=1` to
  inspect individual probes.
- `GET /api/v1/status` → reports uptime, worker state and connection summaries for the UI dashboard.
- `GET /api/v1/health` → returns the backend liveness payload under the versioned `/api/v1` base path.
- `GET /api/v1/metrics` → exposes the Prometheus scrape endpoint.

Details and CLI self-check instructions live in [`docs/health.md`](docs/health.md).

## Spotify OAuth (PRO mode)

Harmony defaults to the Spotify redirect URI `http://127.0.0.1:8888/callback`. When the
server runs remotely, replace `127.0.0.1` in the callback URL with the reachable host
(e.g. `http://192.168.1.5:8888/...`) or forward the port via SSH. You can always finish
an authorization by POSTing the full redirect URL to `/api/v1/oauth/manual`.

A complete walkthrough and troubleshooting tips are in
[`docs/auth/spotify.md`](docs/auth/spotify.md).

## Architecture

The backend, workers and HDM share one process. HDM coordinates ingest pipelines,
communicates with Spotify and Soulseek, and publishes structured logs for observability.
An architectural overview, HDM internals and operational guides are linked from the
documentation hub in [`docs/README.md`](docs/README.md). Highlights include:

- [`docs/overview.md`](docs/overview.md)
- [`docs/architecture/hdm.md`](docs/architecture/hdm.md)
- [`docs/install/docker.md`](docs/install/docker.md)
- [`docs/troubleshooting.md`](docs/troubleshooting.md)

## Support & policies

- Operations & incidents: see the [HDM runbook](docs/operations/runbooks/hdm.md) and
  [`docs/troubleshooting.md`](docs/troubleshooting.md).
- Security guidelines: [`SECURITY.md`](SECURITY.md).
- Contribution workflow and task template: [`docs/task-template.md`](docs/task-template.md).

## License

No explicit license file is published. Unless otherwise stated, all rights are reserved.
For usage or redistribution questions contact the maintainers.
