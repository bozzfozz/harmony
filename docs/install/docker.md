# Docker Installation Guide

Harmony ships as a single container image that exposes the FastAPI backend on
**port 8080**. SQLite is the only supported database; the container creates and
maintains `harmony.db` inside the `/data` volume.

## Prerequisites

- Docker 20.10 or newer.
- Spotify and Soulseek credentials (if you intend to enable HDM PRO flows).
- Host directories for persistent storage:
  - `/downloads` – temporary workspace for HDM downloads.
  - `/music` – final library location managed by HDM.
  - Optional: `/data/runtime/oauth_state` when using the OAuth split mode.

## Quickstart (`docker run`)

```bash
docker run -d \
  --name harmony \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -v $(pwd)/data/downloads:/downloads \
  -v $(pwd)/data/music:/music \
  ghcr.io/bozzfozz/harmony:1.0.0
```

- Mount `/data` to persist the SQLite database (`harmony.db`) and generated
  configuration (`harmony.yml`). Replace `$(pwd)/data` with the host directory
  that should hold these files.
- Mount `/downloads` and `/music` to persist downloads and the organised library.
- Harmony creates missing directories on start-up.
- Optional security hardening:
  - `HARMONY_API_KEYS` enables API key authentication (comma-separated list).
  - `ALLOWED_ORIGINS` restricts CORS; defaults to `*` when unset.
  - Provide them via `-e ...` flags or a `.env` file when exposing Harmony
    beyond trusted networks.
- The first boot writes `/data/harmony.yml` with every supported configuration
  toggle. Update the YAML to persist overrides; environment variables still win
  when both sources specify a value.

Verify the deployment:

```bash
curl -fsS http://127.0.0.1:8080/live
curl -fsS http://127.0.0.1:8080/api/health/ready?verbose=1
```

Both commands must return HTTP 200. The ready endpoint prints dependency details when
`verbose=1` is supplied.

To retrofit the `/data` mount on an existing container, create the persistent
host directory, copy `harmony.db` and `harmony.yml` out of the container
(`docker cp harmony:/data/harmony.db ./data/ && docker cp harmony:/data/harmony.yml ./data/`),
stop the container, and restart it with the extra `-v ...:/data` flag. Harmony
will reuse the copied files on the next boot.

## Using docker compose

[`compose.yaml`](../../compose.yaml) is the canonical docker compose definition:

```yaml
services:
  harmony:
    image: ghcr.io/bozzfozz/harmony:1.0.0
    container_name: harmony
    environment:
      TZ: Etc/UTC
      PUID: "1000"
      PGID: "1000"
    volumes:
      - /mnt/harmony:/data
      - /mnt/data/downloads:/downloads
      - /mnt/data/music:/music
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:8080/api/health/ready || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s
    restart: unless-stopped
```

The host paths under `/mnt/...` are only examples—point them at your persistent
storage and library directories. Harmony boots without additional environment
variables, leaving API keys disabled by default. Keep the compose stack on a
trusted network or set `HARMONY_API_KEYS` in a `.env` file (or inline) before
publishing the service. The generated `/data/harmony.yml` contains every tunable
value; edit it to adjust defaults and commit the file to source control if
desired. Supply `ALLOWED_ORIGINS` alongside the keys when you want to tighten
security. Add further overrides as needed (for example,
`OAUTH_SPLIT_MODE=true` plus a `/data/runtime/oauth_state` mount when running OAuth
flows across multiple containers).

The published release identifier comes from [`app/version.py`](../../app/version.py)
and is exposed via the `/live` probe. Pin your deployments to `1.0.0` (or the
current constant) instead of `latest` to ensure reproducible upgrades.

Bring the stack up with:

```bash
docker compose up -d
```

## SQLite Backups

Harmony writes `harmony.db` into the `/data` volume. To back it up safely:

1. Stop the container or ensure no writes occur (`docker stop harmony`).
2. Copy `/data/harmony.db` from the host volume.
3. Restart the container (`docker start harmony`).

Avoid copying the database while the service is actively writing to it to prevent
corrupted snapshots.
