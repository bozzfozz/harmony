# Harmony Docker Startup Diagnostics & Recovery Plan

## Scope & Invariants
- Applies to container launches driven by the published Harmony image and `scripts/docker-entrypoint.sh`.
- Startup **must** complete `app.runtime.container_entrypoint.main()` without raising `BootstrapError`/`EntrypointError`; otherwise the process exits immediately.
- Writable directories for downloads and music **must** exist before `uvicorn` starts because the entrypoint validates and touches them (`ensure_directory`).【F:app/runtime/container_entrypoint.py†L242-L320】
- The effective SQLite database URL defaults to the profile-specific value resolved by `resolve_default_database_url()`; container profiles fall back to `/config/harmony.db` when `DATABASE_URL` is unset, so that directory must remain writable.【F:app/runtime/container_entrypoint.py†L269-L314】【F:app/config.py†L1167-L2140】

## Observed Symptoms
- `curl http://127.0.0.1:8080/api/health/live` returns `connection reset` and subsequently `couldn’t connect`, indicating the process dies shortly after binding.
- Docker container exits on boot; port 8080 closes before the health probe reruns.
- SQLite database artefacts never appear, implying bootstrap aborted before `ensure_sqlite_database()` finished or the directory is read-only.

## Root-Cause Hypotheses
1. **Missing bind-mounts for runtime directories**
   - Entry point enforces the existence, ownership and rw-access for `/downloads` & `/music` (or overrides). Failure raises `BootstrapError`, terminating the container.【F:app/runtime/container_entrypoint.py†L210-L320】
   - Smoke environment lacks `/downloads` and `/music` mounts, so the paths resolve to the container filesystem → bootstrap aborts when it cannot create them.
2. **Health probe hitting legacy path**  
   - Container exposes `/api/health/live` as the canonical liveness path; `/live` is configurable but defaults to the legacy stub for backwards compatibility.【F:app/runtime/container_entrypoint.py†L340-L404】
   - Probes against `/live` may succeed even when the canonical endpoint fails, masking real readiness regressions. Update automation to target `/api/health/live`.
3. **SQLite bootstrap blocked**
   - When no `DATABASE_URL` is provided, Harmony stores `harmony.db` under `/config`; read-only mounts or volume misconfiguration prevent file creation, triggering a `BootstrapError`.【F:app/runtime/container_entrypoint.py†L269-L314】

## Diagnosis Workflow
1. **Provision writable volumes**
   ```bash
   TMP=$(mktemp -d)
   python -m scripts.preflight_volume_check \
     --config-dir "$TMP/config" \
     --downloads-dir "$TMP/downloads" \
     --music-dir "$TMP/music"
   ```
2. **Run container with mounts**
   ```bash
   docker run --rm -d --name harmony \
     -e APP_PORT=8080 \
     -e PUID=1000 \
     -e PGID=1000 \
     -e HARMONY_CONFIG_FILE=/config/harmony.yml \
     -e DOWNLOADS_DIR=/downloads \
     -e MUSIC_DIR=/music \
      -p 8080:8080 \
      -v "$TMP/config":/config \
      -v "$TMP/downloads":/downloads \
      -v "$TMP/music":/music \
      ghcr.io/bozzfozz/harmony:latest
   ```
3. **Stream logs immediately**  
   ```bash
   docker logs -f harmony
   ```
   - Look for `startup` log lines emitted by the entrypoint; failures include precise `path=` metadata.
4. **Probe correct health endpoints**  
   ```bash
   curl -fsS http://127.0.0.1:8080/api/health/live
   curl -fsS http://127.0.0.1:8080/api/health/ready?verbose=1
   ```
5. **Validate database artefact**
   ```bash
   ls -l "$TMP/config"/harmony.db "$TMP/config"/harmony.yml
   ```
   - If SQLite path differs (custom `DATABASE_URL`), verify parent directory permissions align with `PUID/PGID`.

## Remediation Plan
1. **CI smoke test hardening**
   - Mount ephemeral tmpfs-backed directories for `/downloads`, `/music`, and `/config` before starting the container.
   - Use `/api/health/live` (liveness) plus optional `/api/health/ready` for readiness in the loop.
   - Capture logs on failure by trapping `ERR` and ensuring container cleanup.
2. **Runtime resilience**
   - Ensure `bootstrap_environment` plus `ensure_sqlite_database` create `/config` (if configured) with the same guard rails as downloads/music.
   - Surface misconfigurations through structured log messages to aid automated detection.
3. **Observability & Testing**
   - Add regression tests asserting that `bootstrap_environment` raises a `BootstrapError` when directories are missing or read-only.
   - Provide documentation snippet in Docker install guide explaining required volume layout and health endpoints.

## Alternative Approaches
| Option | Pros | Cons |
| --- | --- | --- |
| Lazy-create directories inside request handlers | Simplifies bootstrap requirements | Defers failure until user interaction; harder to debug under automation |
| Switch default SQLite path to `/config/harmony.db` (current default) | Aligns with expectation of config volume | Requires migration for existing deployments; still needs writable parent |
| Ship default tmpfs volumes baked into container | No host mounts required | Breaks persistence expectations; data lost on restart |

**Chosen approach:** Harden bootstrap + smoke harness. It fails fast with actionable errors, keeps persistent storage under operator control, and maintains backward compatibility.

## Verification Checklist
- [ ] Smoke test succeeds with CI harness changes.
- [ ] `/api/health/live` returns `200` within 60 s of container start.
- [ ] SQLite database file is created when running without external `DATABASE_URL`.
- [ ] Entry point logs show directory validation succeeded for downloads/music/config.
