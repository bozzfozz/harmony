# Harmony

Harmony is a FastAPI backend that unifies Spotify metadata, Soulseek downloads and local
post-processing into a single automation-friendly music hub. The unified container
exposes the API on **port 8080** and stores all state in SQLite.

> **Frontend status:** Harmony ships a server-side rendered FastAPI + Jinja2 + HTMX UI
> under `/ui`. Operators can reach dashboards, operations, downloads, jobs, watchlists,
> settings and system panels via the `/ui/...` routes defined in
> [`app/ui/routes`](app/ui/routes). Reference [`docs/ui/fe-htmx-plan.md`](docs/ui/fe-htmx-plan.md)
> for the sitemap & fragment contracts, [`docs/operations/security.md`](docs/operations/security.md)
> for session and role guidance, [`docs/ui/csp.md`](docs/ui/csp.md) for CSP controls, and
> [`docs/ui/spotify.md`](docs/ui/spotify.md) plus [`docs/ui/soulseek.md`](docs/ui/soulseek.md)
> for feature-specific flows. No Node.js build step is required, but install Node.js ≥ 18 to
> run the bundled UI bootstrap tests (see [`tests/ui/test_ui_bootstrap.py`](tests/ui/test_ui_bootstrap.py)).

## Highlights

- **Harmony Download Manager (HDM):** Orchestrates watchlists, ingest jobs and
  enrichment workers, writing downloads to `/downloads` and promoting verified
  tracks into `/music`.
- **Unified Image:** One container delivers API, background workers and UI with a single
  exposed port and health surface.
- **Provider Integrations:** Spotify PRO (OAuth) and FREE flows plus Soulseek (slskd)
  provide matching, downloads and metadata enrichment.

See the extended overview in [`docs/overview.md`](docs/overview.md).
Operator-facing documentation is curated in
[`docs/user/README.md`](docs/user/README.md), while engineering guardrails live
in [`docs/ai/README.md`](docs/ai/README.md).

## Quickstart

### `docker run`

```bash
docker run -d \
  --name harmony \
  -p 8080:8080 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Etc/UTC \
  -v $(pwd)/config:/config \
  -v $(pwd)/downloads:/downloads \
  -v $(pwd)/music:/music \
  lscr.io/linuxserver/harmony:latest
```

- Mount `/config` to persist the SQLite database (`harmony.db`) and the
  generated configuration file (`harmony.yml`). Replace `$(pwd)/config` with
  the host directory that should store both files. Harmony creates them on
  first boot when they are missing.
- Mount `/downloads` and `/music` to persist downloads and the organised
  library.
- Harmony boots without API keys so the Quickstart stays local-friendly. Restrict
  the container to trusted networks or define `HARMONY_API_KEYS` before exposing
  it beyond your LAN.
- Optional security hardening:
  - `HARMONY_API_KEYS` enables API key authentication (comma-separated list).
  - `ALLOWED_ORIGINS` restricts CORS; defaults to `*` when unset.
  - `PUID`/`PGID` (default `1000`) align the container user and group with the mounted
    volumes. The entrypoint prepares the directories and then drops privileges to the
    configured IDs before starting Uvicorn.
  - Provide them via `-e ...` flags or a `.env` file when exposing Harmony
    beyond trusted networks.
- Edit `/config/harmony.yml` to tailor Harmony; environment variables still win
  over values defined in the YAML.
- Verify the deployment with `curl -fsS http://127.0.0.1:8080/api/health/live` and
  `curl -fsS "http://127.0.0.1:8080/api/health/ready?verbose=1"`.
  The versioned system endpoints live under `/api/v1/...`; see
  [`docs/ui/fe-htmx-plan.md`](docs/ui/fe-htmx-plan.md) for the UI wiring overview.

Existing deployments can adopt the `/config`, `/downloads` and `/music` mounts
by creating the host directories, copying `harmony.db` and `harmony.yml` out of
the running container (`docker cp harmony:/config/harmony.db ./config/ &&
docker cp harmony:/config/harmony.yml ./config/`), stopping the container, and
starting it again with the additional `-v ...:/config`, `-v ...:/downloads`,
and `-v ...:/music` flags. Harmony reuses the copied files on boot.

The LinuxServer.io docker compose example ships in
[`docker-compose.yml`](docker-compose.yml). Adjust the host paths to match your environment
and see [`docs/install/docker.md`](docs/install/docker.md) for additional
deployment notes.

> The canonical backend version lives in [`app/version.py`](app/version.py).
> Harmony v**1.0.0** exposes the same number via `/api/health/live`, `/live`, `/env`
> and the OpenAPI schema so pinned deployments and health checks stay in sync.

## Minimal configuration

Harmony boots with sensible defaults and only needs overrides for specific
deployments. Key options:

| Variable | Default | Purpose | When to set |
| --- | --- | --- | --- |
| `HARMONY_API_KEYS` | _(empty)_ | Enables API key authentication. | Recommended when Harmony is reachable from untrusted networks. |
| `ALLOWED_ORIGINS` | `*` | CORS allowlist for the browser UI. | Set to your public base URL when tightening CORS. |
| `UI_COOKIES_SECURE` | `false` | Marks UI session, CSRF and pagination cookies as `Secure`. | Enable behind TLS; default stays `false` to support local HTTP testing. |
| `DOWNLOADS_DIR` | `/downloads` | Workspace for HDM downloads. | Override when the downloads path differs from the default mount. |
| `MUSIC_DIR` | `/music` | Target library for organised media. | Override when the music library lives elsewhere. |
| `harmony.yml` | auto-generated | YAML file under `/config/harmony.yml` containing every tunable variable. | Edit to persist configuration between restarts. |

All other knobs are documented in [`docs/configuration.md`](docs/configuration.md).

Harmony expects the UI to sit behind HTTPS so that `Secure` cookies are honoured end-to-end.
Set `UI_COOKIES_SECURE=true` as soon as TLS terminates in front of Harmony; the `false`
default exists purely to simplify ad-hoc local testing on HTTP. Keep HTTP deployments on a
trusted network.

## Health checks

- `GET /api/health/live` → returns `{ "status": "ok" }` without touching external dependencies.
  `/live` remains available as a backwards-compatible alias.
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
An architectural overview, HDM internals and operational guides are linked from
the audience hubs in [`docs/user/README.md`](docs/user/README.md) and
[`docs/ai/README.md`](docs/ai/README.md). Highlights include:

- [`docs/overview.md`](docs/overview.md)
- [`docs/architecture/hdm.md`](docs/architecture/hdm.md)
- [`docs/install/docker.md`](docs/install/docker.md)
- [`docs/troubleshooting.md`](docs/troubleshooting.md)

## Dependency management

Runtime dependencies are pinned in [`requirements.txt`](requirements.txt) and power the
production Docker image. Local development installs the runtime stack first, then tooling
and test libraries:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt -r requirements-test.txt
```

`requirements-dev.txt` provides linting and static-analysis tools, while
`requirements-test.txt` contains pytest and asyncio fixtures for the test suite. Regenerate
the pins with [`pip-compile`](https://pip-tools.readthedocs.io/) when dependency upgrades
are introduced.

> **Security note:** FastAPI is pinned to 0.116.1, the latest PyPI release. Starlette is
> locked to 0.49.1 explicitly to incorporate the GHSA-7f5h-v6xp-fcq8 Range header DoS
> fix. Monitor upstream for additional 0.49.x hotfixes or behavioural changes before
> adjusting the stack.

## Release gate

Run `make release-check` (or the legacy alias `make Release`) before tagging or publishing a release. The target now delegates
to `scripts/dev/release_check.py`, which executes the full backend and UI gate (`make
all`), verifies documentation references (`make docs-verify`), audits all
`requirements*.txt` pins for known vulnerabilities via `make pip-audit`, and finishes
with the UI smoke test. The script emits structured JSON logs and stops immediately after
the first failing command to preserve the previous error context. Use `python
scripts/dev/release_check.py --dry-run` to inspect the planned steps without executing
them, or override the executed commands in CI with
`RELEASE_CHECK_COMMANDS="<cmd1>\n<cmd2>"` for targeted verifications. Ensure the
[`pip-audit`](https://pypi.org/project/pip-audit/) CLI from `requirements-dev.txt` is
installed and that network access is available so the security scan can complete without
downgrading the gate.

When preparing the LinuxServer.io image, build it with `make image-lsio` and verify the
runtime with `make smoke-lsio`. The smoke harness boots the freshly built container,
waits up to 60 seconds for `/api/health/ready`, and confirms that `/config/harmony.db`
exists. Capture the resulting logs for your release evidence alongside the other gates.

## Support & policies

- Operations & incidents: see the [HDM runbook](docs/operations/runbooks/hdm.md) and
  [`docs/troubleshooting.md`](docs/troubleshooting.md).
- Security guidelines: [`SECURITY.md`](SECURITY.md).
- Contribution workflow and task template: [`docs/task-template.md`](docs/task-template.md).

## License

Harmony is licensed under the [MIT License](LICENSE). Refer to the license text for
permissions, limitations and contributor terms.
