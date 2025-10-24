# Harmony Download Manager (HDM)

The Harmony Download Manager orchestrates every ingest, download and post-processing
step in the unified backend. It replaces the legacy `download_flow`/`hdl` modules and is
the canonical entrypoint for automating library updates.

## Responsibilities

1. **Orchestration** – The `app.hdm.orchestrator` module accepts jobs (watchlist,
   backfill, manual downloads) and fans them out to specialised worker pools. HDM
   enforces queue priorities, visibility timeouts and retry budgets.
2. **Acquisition** – Workers communicate with Spotify and slskd to match desired tracks,
   request downloads and monitor job status. All network calls honour the provider
   timeout and retry policies defined in configuration.
3. **Tagging & Enrichment** – After the payload reaches `/data/downloads`, HDM invokes
   metadata, artwork and lyrics processors (when enabled) to embed complete tags before
   promoting files into `/data/music`.
4. **Movement & Deduplication** – The `AtomicFileMover` ensures durable moves within or
   across filesystems. Deduplication guards skip already ingested tracks and keep a
   persistent audit trail.
5. **Recovery** – Failed jobs emit structured `hdm.recovery.*` logs and land in the
   DLQ tables exposed through the `/api/v1/dlq` APIs. Operators manage retries via the
   DLQ endpoints and dashboards, while HDM surfaces status metrics for observability.

## Runtime Layout

- `app/hdm/orchestrator.py` – Queue coordination and worker scheduling.
- `app/hdm/workers/*` – Specialised workers (matching, download, tagging, move).
- `app/services/*` – Shared services (backfill, secret store, retry policies) consumed by
  HDM.
- `app/routers/download_router.py` – API surface for submitting HDM jobs.

The container entrypoint configures HDM using the same environment variables as the API;
no separate services are required.

## Operational Contracts

- Jobs are idempotent. Duplicate submissions collapse into a single queue entry and
  return `already_enqueued` where applicable.
- Idempotency reservations are persisted in SQLite by default under
  `<downloads_dir>/.harmony/idempotency.db`, ensuring restarts do not reprocess
  completed tracks. Deployments can fall back to the in-memory backend for
  ephemeral test runs.
- Volume expectations:
  - `/data/downloads` must support writes, renames and `fsync`. Cross-device moves
    trigger copy-and-rename fallbacks handled by HDM.
  - `/data/music` must be writable by the container user (configurable via `PUID`/`PGID`).
- Readiness gating: HDM delays worker startup until the readiness checks pass to avoid
  running against half-configured providers.
- Structured logs use the `hdm.*` namespaces for easy filtering. Key events include
  `hdm.match.enqueued`, `hdm.move.completed`, `hdm.dedupe.skipped` and
  `hdm.recovery.requeued`.

## Related Documents

- [HDM Runbook](../operations/runbooks/hdm.md) – Operational procedures and recovery steps.
- [HDM Audit](../compliance/hdm_audit.md) – Compliance and traceability evidence.
- [docs/auth/spotify.md](../auth/spotify.md) – Spotify OAuth configuration required for
  PRO mode.
