# Docker Installation Guide

Harmony ships as a single container image that exposes the FastAPI backend on
**port 8080**. SQLite is the only supported database; the container creates and
maintains `harmony.db` inside the `/config` volume.

## Prerequisites

- Docker 20.10 or newer.
- Spotify and Soulseek credentials (if you intend to enable HDM PRO flows).
- Host directories for persistent storage:
  - `/config` – stores the SQLite database (`harmony.db`) and (optionally) backups.
  - `/data` – receives the generated `harmony.yml` configuration file.
  - `/downloads` – temporary workspace for HDM downloads.
  - `/music` – final library location managed by HDM.
  - Optional: `/config/runtime/oauth_state` when using the OAuth split mode.

Prepare the directories and align their ownership with the container user
before starting Harmony:

```bash
python -m scripts.preflight_volume_check
```

The preflight script creates `volumes/config`, `volumes/data`,
`volumes/downloads`, and `volumes/music` relative to the repository. Override
`--config-dir`, `--data-dir`, `--downloads-dir`, or `--music-dir` to point at
different host paths. Use `--puid/--pgid` when you want to pre-provision the
directories for another UID/GID combination.

## Quickstart (`docker run`)

```bash
docker run -d \
  --name harmony \
  -p 8080:8080 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e HARMONY_CONFIG_FILE=/config/harmony.yml \
  -e DOWNLOADS_DIR=/downloads \
  -e MUSIC_DIR=/music \
  -v $(pwd)/volumes/config:/config \
  -v $(pwd)/volumes/data:/data \
  -v $(pwd)/volumes/downloads:/downloads \
  -v $(pwd)/volumes/music:/music \
  ghcr.io/bozzfozz/harmony:1.0.0
```

- Mount `/config` to persist the SQLite database (`harmony.db`). Replace
  `$(pwd)/volumes/config` with the host directory that should hold the database.
- Mount `/data` to persist the generated configuration (`harmony.yml`). Replace
  `$(pwd)/volumes/data` with the host directory that should hold the file.
- Mount `/downloads` and `/music` to persist downloads and the organised
  library.
- Mount `/config` to keep configuration assets separate from application data.
- `scripts/preflight_volume_check.py` ensures the directories exist and are
  writable for the configured `PUID`/`PGID`.
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
curl -fsS http://127.0.0.1:8080/api/health/live
curl -fsS http://127.0.0.1:8080/api/health/ready?verbose=1
```

Both commands must return HTTP 200. The ready endpoint prints dependency details when
`verbose=1` is supplied.

To retrofit the `/config` and `/data` mounts on an existing container, create
the persistent host directories, copy `harmony.db` and `harmony.yml` out of the
container (`docker cp harmony:/config/harmony.db ./config/ && docker cp
harmony:/data/harmony.yml ./data/`), stop the container, and restart it with the
extra `-v ...:/config` and `-v ...:/data` flags. Harmony will reuse the copied
files on the next boot.

## Using docker compose

Run the preflight step once (or after changing the volume locations) to provision
the directories:

```bash
python -m scripts.preflight_volume_check
```

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
      HARMONY_CONFIG_FILE: /config/harmony.yml
      DOWNLOADS_DIR: /downloads
      MUSIC_DIR: /music
    volumes:
      - ./volumes/config:/config
      - ./volumes/data:/data
      - ./volumes/downloads:/downloads
      - ./volumes/music:/music
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

The host paths above assume you run `docker compose` from the repository root.
Adjust them when the host directories live elsewhere (use absolute paths for
remote disks). Harmony boots without additional environment
variables, leaving API keys disabled by default. Keep the compose stack on a
trusted network or set `HARMONY_API_KEYS` in a `.env` file (or inline) before
publishing the service. The generated `/data/harmony.yml` contains every tunable
value; edit it to adjust defaults and commit the file to source control if
desired. Supply `ALLOWED_ORIGINS` alongside the keys when you want to tighten
security. Add further overrides as needed (for example,
`OAUTH_SPLIT_MODE=true` plus a `/config/runtime/oauth_state` mount when running OAuth
flows across multiple containers).

The published release identifier comes from [`app/version.py`](../../app/version.py)
and is exposed via the `/live` probe. Pin your deployments to `1.0.0` (or the
current constant) instead of `latest` to ensure reproducible upgrades.

Bring the stack up after the preflight succeeded:

```bash
docker compose up -d
```

## SQLite Backups

Harmony writes `harmony.db` into the `/config` volume. To back it up safely:

1. Stop the container or ensure no writes occur (`docker stop harmony`).
2. Copy `/config/harmony.db` from the host volume.
3. Restart the container (`docker start harmony`).

Avoid copying the database while the service is actively writing to it to prevent
corrupted snapshots.
