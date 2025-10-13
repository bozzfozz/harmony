# Docker Installation Guide

Harmony ships as a single container image that exposes both the FastAPI backend and the
static web UI on **port 8080**. SQLite is the only supported database; the container
creates and maintains `harmony.db` inside the `/data` volume.

## Prerequisites

- Docker 20.10 or newer.
- Spotify and Soulseek credentials (if you intend to enable HDM PRO flows).
- Host directories for persistent storage:
  - `/data/downloads` – temporary workspace for HDM downloads.
  - `/data/music` – final library location managed by HDM.
  - Optional: `/data/runtime/oauth_state` when using the OAuth split mode.

## Quickstart (`docker run`)

```bash
docker run -d \
  --name harmony \
  -p 8080:8080 \
  -e HARMONY_API_KEYS=change-me \
  -e ALLOWED_ORIGINS=http://localhost:8080 \
  -e PUBLIC_BACKEND_URL=http://localhost:8080 \
  -v $(pwd)/data/downloads:/data/downloads \
  -v $(pwd)/data/music:/data/music \
  ghcr.io/bozzfozz/harmony:latest
```

- `HARMONY_API_KEYS` accepts a comma-separated list. Replace `change-me` with an actual
  secret before exposing the service.
- `ALLOWED_ORIGINS` and `PUBLIC_BACKEND_URL` should point to the public base URL that
  the frontend uses to call the API.
- Harmony creates missing directories on start-up and keeps the SQLite database at
  `/data/harmony.db`.

Verify the deployment:

```bash
curl -fsS http://127.0.0.1:8080/live
curl -fsS http://127.0.0.1:8080/api/health/ready?verbose=1
```

Both commands must return HTTP 200. The ready endpoint prints dependency details when
`verbose=1` is supplied.

## Using docker compose

The repository includes a single-service [`compose.yaml`](../../compose.yaml) matching
the runtime defaults.

```bash
docker compose up -d
open http://localhost:8080
```

Key options:

- `ports: "8080:8080"` exposes the API/UI on the host.
- `volumes` mount `/data/downloads` and `/data/music` from the host for persistence.
- `OAUTH_SPLIT_MODE=true` requires a shared mount at `/data/runtime/oauth_state` and
  should be combined with the same UID/GID across all participating containers.

To override settings, place a `.env` file next to `compose.yaml` or export environment
variables before running `docker compose up`.

## SQLite Backups

Harmony writes `harmony.db` into the `/data` volume. To back it up safely:

1. Stop the container or ensure no writes occur (`docker stop harmony`).
2. Copy `/data/harmony.db` from the host volume.
3. Restart the container (`docker start harmony`).

Avoid copying the database while the service is actively writing to it to prevent
corrupted snapshots.
