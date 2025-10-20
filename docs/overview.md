# Harmony Overview

Harmony is a FastAPI-based backend that aggregates Spotify, Soulseek (slskd) and local
processing pipelines into a single music automation hub. It provides a unified JSON API
for frontends and automation clients, coordinates ingest and enrichment jobs, and
persists all state in a single SQLite database that ships inside the container image.

## Core Components

- **Public API & UI** – The web UI and HTTP API share the same process and are served
  from the unified container on port 8080.
- **Harmony Download Manager (HDM)** – The orchestrator responsible for matching,
  downloading, tagging and moving media into the managed library. HDM owns the queueing
  model, recovery flow and deduplication logic.
- **Integrations** – Spotify (PRO and FREE flows) and Soulseek provide metadata and
  files. Additional utility services (lyrics, artwork, observability) are opt-in via
  feature flags. See the [Soulseek UI dashboard guide](ui/soulseek.md) for day-to-day
  operations on `/ui/soulseek`.
- **Background Workers** – Watchlist, matching and enrichment workers run inside the
  same container process and respect the global HDM contracts.

## How the Pieces Fit Together

1. API clients or the web UI create jobs (watchlist entries, ingest batches, manual
   downloads) via authenticated HTTP calls.
2. HDM orchestrates the jobs, talks to the provider integrations and writes downloads
   into `/data/downloads` before promoting validated tracks into `/data/music`.
3. Post-processing workers enrich the tracks (metadata, lyrics, artwork) and expose the
   results through API endpoints and the UI.
4. Health and observability surfaces expose system readiness, HDM queues and
   integration status.

Further architectural diagrams and contracts live under
[`docs/architecture/`](architecture/). HDM-specific internals are documented in
[`docs/architecture/hdm.md`](architecture/hdm.md) and operational procedures are
covered in [HDM runbook](operations/runbooks/hdm.md).
