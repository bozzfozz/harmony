# Spotify UI Operations Guide

This guide explains how operators use the `/ui/spotify` page to monitor and
manage Spotify integrations inside Harmony. It focuses on day-to-day
activities—role requirements, feature flags, and recovery tips—while
engineering implementation notes remain documented in
[`docs/ui/fe-htmx-plan.md`](fe-htmx-plan.md).

## Audience & Prerequisites
- **Intended roles:** The page requires at least the `operator` role. Specific
  actions may escalate to `admin`; see each card below.
- **Feature flags:** `UI_FEATURE_SPOTIFY=true` is mandatory. FREE ingest panels
  additionally require `UI_FEATURE_IMPORTS=true`.
- **Environment readiness:** Confirm Spotify OAuth secrets are valid and
  `GET /spotify/status` reports `authorized: true` before relying on the UI.

## Card Overview
| Card | Purpose | Minimum role | Required flags |
| --- | --- | --- | --- |
| Status | Connection state, error banners, next steps | operator | `UI_FEATURE_SPOTIFY` |
| Account | Displays Spotify profile, subscription tier, scopes | operator (view) / admin (scope reset) | `UI_FEATURE_SPOTIFY` |
| Playlists | Lists managed playlists and sync posture | operator | `UI_FEATURE_SPOTIFY` |
| Recommendations | Surfaces seed-driven track suggestions for ingest/watchlist | operator | `UI_FEATURE_SPOTIFY` |
| Saved tracks | Shows most recent liked tracks and allows queuing/removal | operator (view) / admin (bulk removal) | `UI_FEATURE_SPOTIFY` |
| FREE ingest | Drag-and-drop or paste-based submissions for FREE ingestion | operator | `UI_FEATURE_SPOTIFY`, `UI_FEATURE_IMPORTS` |
| Backfill | Starts and tracks catalog backfill jobs | operator (view) / admin (cancel) | `UI_FEATURE_SPOTIFY` |

## Status Card
- **What it shows:** Current Spotify connectivity (`connected`,
  `unauthenticated`, or `unconfigured`), FREE/PRO availability flags, and the
  timestamp of the last successful poll.
- **Primary actions:** Quick links to rerun OAuth and open the OAuth runbook.
  No additional privileges required beyond page access.
- **Operational expectations:** The badge should stay green (`connected`).
  Yellow indicates credential expiry; red indicates missing configuration.
- **FREE badge semantics:** The FREE badge switches to `Disabled` when Soulseek
  prerequisites are missing (base URL or API key) or when the daemon health
  check fails. Inspect application logs for
  `spotify.free_ingest.unavailable` entries to identify the reason.
- **Observability hooks:** Uses `GET /api/v1/spotify/status` with 60‑second
  polling; structured logs emit `oauth.service` events when state changes.

## Account Card
- **What it shows:** Display name, email, product tier (Free/Premium), country,
  and granted scopes sourced from `GET /api/v1/spotify/me` and related profile
  endpoints.
- **Primary actions:** "Reset scopes" (admin only) clears stored tokens so the
  next OAuth flow requests missing permissions. Operators may refresh profile
  data.
- **Operational expectations:** Scopes must include playlist modify/read rights
  for ingest and backfill features. Mismatched scopes trigger an inline warning.
- **Observability hooks:** Profile refresh failures surface as toast warnings;
  audit logs capture scope resets for compliance.

## Playlists Card
- **What it shows:** All playlists tracked by Harmony, playlist ownership,
  follower counts, and cache freshness indicators derived from
  `GET /api/v1/spotify/playlists`.
- **Primary actions:** Operators can filter by owner or sync status, request a
  playlist refresh, and open details (tracks, sync history). Admins can invoke
  "force sync" when cache drift is detected.
- **Operational expectations:** Cached playlists should refresh automatically
  via worker jobs; the UI primarily offers verification and spot refresh.
- **Observability hooks:** Uses ETag/Last-Modified headers to avoid redundant
  fetches; any `304` responses are logged as debug events for cache auditing.

### Playlist Sync Status Policy
- **Data source:** `PlaylistSyncWorker` stores `sync_status`,
  `sync_status_reason`, and `synced_at` in each playlist's metadata. The
  `synced_at` timestamp is persisted in ISO format (UTC) for downstream audits.
- **Fresh (`sync_status=fresh`):** The most recent Spotify snapshot matches the
  previously stored snapshot, and the worker has re-synced the playlist within
  the two-hour service-level window.
- **Stale (`sync_status=stale`):** Any of the following: the Spotify snapshot ID
  differs from the prior value (`sync_status_reason=snapshot_changed`), Spotify
  omits the snapshot (`missing_snapshot`), the elapsed time between successive
  worker runs exceeds two hours (`sync_gap`), or the playlist was already marked
  stale by dependent workflows (`previously_stale`).
- **Follow-up actions:** Use "force sync" to prioritise a refresh when
  `sync_status_reason` is `snapshot_changed` or `missing_snapshot`. Investigate
  worker health if `sync_gap` appears, as it signals the SLA was missed.

## Recommendations Card
- **What it shows:** Track suggestions based on configured seeds (tracks,
  artists, genres) using `GET /api/v1/spotify/recommendations`.
- **Primary actions:** Operators curate seed sets, preview matching tracks, and
  queue promising items for ingest. Admins may pin default seeds for the team.
- **Feature dependency:** Queue buttons only appear when `UI_FEATURE_IMPORTS`
  is enabled. If imports are disabled, the UI hides queue controls and the
  server responds with `404` to queue submissions.
- **Operational expectations:** Seeds persist per session; expect varied
  results depending on available audio features and saved history.
- **Observability hooks:** Recommendation payload sizes and latency surface via
  application metrics (`spotify.recommendations.latency_ms`).

## Saved Tracks Card
- **What it shows:** Recently liked tracks (`GET /api/v1/spotify/me/top/tracks`
  and saved items) along with action buttons to add items to ingest queues or
  remove them from the saved list.
- **Primary actions:** Operators enqueue tracks into Harmony's ingest pipeline;
  admins can bulk remove saved tracks to keep personal libraries tidy.
- **Feature dependency:** Queueing saved tracks also requires
  `UI_FEATURE_IMPORTS=true`; otherwise the queue action is hidden and HTTP
  requests receive `404`.
- **Operational expectations:** Saved items sync within 60 seconds of new likes.
  If the table lags, verify background sync workers.
- **Observability hooks:** Mutations call `POST /api/v1/spotify/me/tracks` and
  `DELETE /api/v1/spotify/me/tracks`; actions log to `spotify.saved_tracks`
  events for auditability.

## FREE Ingest Card
- **What it shows:** Upload widgets for FREE ingest workflows—drag-and-drop
  files, paste URLs, and review submission history powered by
  `/api/v1/spotify/import` routes.
- **Primary actions:** Operators submit CSV/TXT/JSON manifests, validate the
  parsed rows, and send approved batches downstream. Admins may purge stuck jobs
  or reprocess failures.
- **Operational expectations:** Each submission returns a job ID; status polls
  every 15 seconds until completion. Upload size limits mirror the API's
  `MAX_FREE_IMPORT_SIZE` setting.
- **Observability hooks:** Failed validations raise inline error chips and
  propagate to `free_ingest.validation_error` logs; successful imports emit
  `free_ingest.submission.accepted` with the job ID.

## Backfill Card
- **What it shows:** Controls for catalog backfill jobs and a timeline of recent
  runs sourced from `/api/v1/spotify/backfill/*` endpoints.
- **Primary actions:** Operators launch backfill jobs with preset limits, pause
  or resume active jobs, and inspect processed counts. Admins may cancel jobs or
  override playlist expansion settings. Advanced options now include an
  **Include cached results** toggle—checked by default—to reuse previously
  persisted Spotify lookups. Unchecking the box forces every track to be
  re-evaluated against the live API, which is useful when cache entries may be
  stale but increases runtime and rate-limit consumption.
- **Operational expectations:** Backfills should be scheduled during off-peak
  hours; monitor processed vs. matched counters to ensure Free ingest alignment.
  When running without cached results expect higher `cache_misses` values and
  longer job durations.
- **Observability hooks:** Job state transitions surface as toast notifications
  and mirror `spotify.backfill.jobs` metrics (requested, processed, matched).
  The job timeline records whether cached results were used for each historical
  run.

## Troubleshooting
- **Status badge remains red:** Verify Spotify OAuth secrets, then rerun the
  authorization flow. Consult the HDM runbook section “OAuth-Token
  wiederherstellen” if the state fails to clear.
- **Account card missing scopes:** Run "Reset scopes" (admin) and repeat OAuth.
  Missing playlists afterwards usually indicate revoked Spotify app permissions.
- **Playlists not updating:** Check worker health (`/api/health/spotify`) and
  ensure playlist cache invalidation jobs are running. For immediate relief,
  trigger "force sync".
- **Recommendations empty:** Provide at least one seed (track, artist, or
  genre). Empty responses can also happen when the Spotify account lacks enough
  listening history.
- **Saved tracks stale:** Confirm the background sync worker is active and that
  the account has recent plays. Manual refresh is safe and idempotent.
- **FREE ingest job stuck:** Inspect submission history for validation errors,
  then replay via the ingest service CLI or reset with admin privileges.
- **Backfill job halted:** Review the job detail panel for error messages. If
  OAuth expired mid-run, restart the job after reauthorizing Spotify.

## Related References
- Implementation contracts, HTMX targets, and API wiring live in the
  [FastAPI + Jinja2 + HTMX plan](fe-htmx-plan.md). Use that document when
  adjusting templates or endpoints; keep this guide focused on operational use.
- For OAuth procedures and remote callback handling, see
  [`docs/auth/spotify.md`](../auth/spotify.md) and the HDM runbook.
