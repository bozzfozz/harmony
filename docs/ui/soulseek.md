# Soulseek UI Dashboard Guide

The `/ui/soulseek` dashboard helps operators supervise Soulseek connectivity,
file transfers, and per-user tooling from a single page. It aggregates service
status, exposes cleanup actions, and wraps Soulseek router endpoints so that
common interventions stay discoverable without leaving the UI.

## Audience & Prerequisites
- **Minimum role:** Page access requires an authenticated session with the
  `operator` role and the Soulseek feature flag enabled because the route uses
  `require_operator_with_feature("soulseek")`.
- **Elevated actions:** Cancelling transfers, refreshing download assets, and
  running cleanup jobs depend on the `admin` role (`require_admin_with_feature("soulseek")`).
- **Feature flag:** The Soulseek feature must be enabled for the session or the
  navigation entry and fragments will not render.

## Layout at a Glance
| Section | Fragment ID / Target | Polling cadence | Primary role | Purpose |
| --- | --- | --- | --- | --- |
| Status cards | `hx-soulseek-status` → `#hx-soulseek-status` | 60s | operator | Daemon connectivity & provider health |
| Suggested tasks | `soulseek-tasks` card (inline) | — | operator | Tracks recommended remediation steps |
| Configuration | `hx-soulseek-configuration` → `#hx-soulseek-configuration` | manual | operator | Shows slskd + security settings |
| Uploads table | `hx-soulseek-uploads` → `#hx-soulseek-uploads` | 30s | operator (view) / admin (cancel, cleanup) | Lists active/all uploads and admin actions |
| Downloads table | `hx-soulseek-downloads` → `#hx-soulseek-downloads` | 30s | operator (view) / admin (asset refresh, cleanup) | Displays queue state with lyrics/metadata/artwork tools |
| Discography jobs | `hx-soulseek-discography-jobs` → `#hx-soulseek-discography-jobs` | 60s | operator | Monitors queued Soulseek discography requests |
| User profile tools | `hx-soulseek-user-info` → `#hx-soulseek-user-info` | manual | operator | Fetches address, status, and browse progress for a username |
| User directory browser | `hx-soulseek-user-directory` → `#hx-soulseek-user-directory` | manual | operator | Navigates shared folders for a username |

## Status & Suggested Tasks
- The status grid renders daemon connectivity (`soulseek_status`) and provider
  health derived from `ProviderHealthMonitor.check_all()` inside
  `SoulseekUiService`. Suggested task chips are computed from the same datasets
  and evaluate configuration completeness (API key, retry policy, security
  toggles) before emitting structured logs for observability.
- Polling: The status fragment refreshes every 60 seconds; other badges update
  when fragments rerender or actions return.
- Troubleshooting: When the daemon badge degrades, review slskd connectivity and
  provider health results before escalating.

## Configuration Card
- Data source: `SoulseekUiService.soulseek_config()` exposes the slskd
  configuration while `security_config()` contributes authentication and rate
  limiting toggles.
- Display: The table obfuscates the API key (`••••••`), highlights retry/backoff
  policies, and surfaces preferred formats and limits so that operators can
  compare them against runbook defaults.

## Transfers: Uploads & Downloads
- Uploads: The fragment pulls either the active list or the full queue using
  `SoulseekUiService.uploads(include_all=...)`. Admins can cancel individual
  uploads or purge completed entries; both actions re-render the table and emit
  audit logs.
- Downloads: The downloads fragment paginates queue entries and, for admins,
  surfaces buttons to refresh lyrics, metadata, artwork, or remove completed
  jobs. Each action posts back to `/ui/soulseek/download/...` routes, then
  rehydrates the table via HTMX using the stored CSRF token.
- Polling: Both tables poll every 30 seconds, allowing operators to see
  progress without manual refreshes.

## Discography Jobs
- The discography section monitors batched artist jobs. HTMX refreshes the table
  every 60 seconds while operators can open the modal (fragment ID
  `soulseek-discography-job-modal`) to queue new Soulseek artist IDs.

## User Tools
- Profile panel: Submitting the lookup form hydrates the profile, user status,
  and browse status by calling `SoulseekUiService.user_profile`,
  `.user_status`, and `.user_browsing_status`. Operators can retry lookups when
  Soulseek returns transient errors.
- Directory browser: The shared directory explorer leverages
  `SoulseekUiService.user_directory` and exposes parent navigation plus
  directory/file listings. Operators can drill down using generated URLs that
  feed the same fragment.

## Related Implementation References
- UI router endpoints and role gates live in [`app/ui/router.py`](../../app/ui/router.py).
- Aggregated Soulseek data and helper models live in
  [`app/ui/services/soulseek.py`](../../app/ui/services/soulseek.py).
- HTMX fragment wiring (IDs, polling, targets) is defined in
  [`app/ui/context.py`](../../app/ui/context.py).
