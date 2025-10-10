# Backend Deep Scan Report — CODX-P0-ANLY-500

## Executive Summary
- Critical admin artist APIs fail at runtime because the `activity_events` table referenced by models and services has no corresponding migration, leading PostgreSQL to raise `UndefinedTable` errors and blocking every admin endpoint plus multiple test suites. 【F:app/models.py†L168-L183】【b45c06†L137-L176】【f53942†L1-L1】
- Observability coverage is regressing: orchestrator lease events are not emitted to logs and the search router fails to publish `api.request` telemetry, breaking alerting and two instrumentation tests. 【001fdf†L1-L44】【001fdf†L79-L117】
- Runtime configuration paths drifted—`/system/stats` always uses the real `psutil` module despite overrides, `/spotify/status` responses are cached by the middleware so credential changes are never reflected, and playlist cache invalidation does not refresh stale payloads—causing eight downstream test failures. 【1e2e16†L363-L410】【5742eb†L610-L615】【b45c06†L122-L171】【c08376†L152-L230】
- Quality and security gates are stale: the Ruff import rule (`ruff check --select I`) fails on most backend modules and the required static security scan is missing from the toolchain, leaving style and security coverage unmonitored. 【8bf225†L1-L20】【2a7069†L1-L1】
- Test infrastructure side effects (notably admin API fixtures) mutate global FastAPI state, producing OpenAPI drift when the full suite runs. 【e48f80†L48-L79】【b45c06†L137-L171】

## Findings
| ID | Type | Severity | Location | Summary | Recommendation |
| --- | --- | --- | --- | --- | --- |
| F1 | Bug (DB) | P0 | `app/models.py`, migrations | `activity_events` model lacks a migration; admin artist API blows up (`no such table: activity_events`). | Add forward/backfill migration creating `activity_events` with expected indexes; update admin DAO tests to ensure fixture seeds table. |
| F2 | Observability | P1 | `app/orchestrator/scheduler.py` | Scheduler leases never emit `orchestrator.lease` events, so monitoring misses lease churn. | Restore `log_event` propagation for lease emits (e.g. ensure logger instance is correctly shared) and add regression test capturing `caplog`. |
| F3 | Observability | P1 | `app/api/search.py` | Search router does not emit `api.request` events despite `_emit_api_event` call. | Audit `_emit_api_event` fallback and ensure patched logger is invoked; extend instrumentation tests to assert both `_log_event` and compatibility shims fire. |
| F4 | Bug (Config) | P1 | `app/api/system.py` | `_resolve_psutil` ignores dependency overrides, so `/system/stats` cannot be mocked or hardened. | Change resolver to prefer FastAPI dependency overrides/`app.state` before falling back to compat shim; cover with unit test. |
| F5 | Bug (Caching) | P1 | `app/config.py`, cache middleware | Default cache pattern caches all `/spotify/**` responses, hiding credential changes and status updates. | Exclude status/diagnostic endpoints from cache pattern or add targeted cache-busting in status route; add integration test covering credential revocation. |
| F6 | Bug (Workers) | P1 | `app/workers/playlist_sync_worker.py` | Playlist sync persists updates but cached responses remain stale (ETag unchanged, invalidation ineffective). | Investigate timestamp precision and cache invalidation flow; ensure `updated_at` changes even for rapid successive syncs and assert new ETags in tests. |
| F7 | Test Infra | P1 | `tests/api/test_admin_artists.py` | Admin fixture permanently enables admin routes, mutating global OpenAPI schema for later tests. | Reset `FEATURE_ADMIN_API` (and cached routes) in fixture teardown and/or isolate FastAPI app per test module. |
| F8 | Quality | P2 | repo-wide | `ruff check --select I` fails on dozens of backend modules. | Apply Ruff import sorting with repository config and add CI guard. |
| F9 | Security | P2 | tooling | Static security analyser missing from environment (command not found), so secure coding checks never run. | Add a vetted security scanner to dev requirements/CI and document usage. |

## Finding Details
### F1. Missing `activity_events` migration (P0)
- **Evidence:** Admin tests und API-Routen schlagen mit `psycopg2.errors.UndefinedTable: relation "activity_events" does not exist` fehl. 【b45c06†L137-L176】 Das ORM-Modell existiert, aber `rg` findet keine Migration, die `activity_events` anlegt. 【F:app/models.py†L168-L183】【f53942†L1-L1】
- **Impact:** All admin artist endpoints crash, blocking audit/reconcile flows and invalidating six API tests.
- **Recommendation:** Ship an Alembic migration creating `activity_events` plus audit indexes; add smoke test ensuring admin bootstrap seeds the table.
- **Suggested Tests:** `pytest tests/api/test_admin_artists.py -q`, migration downgrade/upgrade, targeted admin smoke.

### F2. Scheduler lease events missing (P1)
- **Evidence:** `test_scheduler_leases_jobs_in_priority_order` captures zero `orchestrator.lease` events even though leases occur. 【001fdf†L1-L44】
- **Impact:** Observability dashboards lose visibility into queue leasing; alerting on stuck leases will not fire.
- **Recommendation:** Verify `log_event` dispatch path in `orchestrator.events.emit_lease_event`; ensure scheduler logger uses middleware-compatible handler; add regression test verifying `caplog` contains lease events.
- **Suggested Tests:** `pytest tests/orchestrator/test_scheduler.py::test_scheduler_leases_jobs_in_priority_order -q`.

### F3. Search router telemetry regression (P1)
- **Evidence:** `test_search_router_emits_api_request_event` fails—no `api.request` event logged despite `_emit_api_event` call. 【001fdf†L79-L117】
- **Impact:** API monitoring misses request lifecycle metrics, harming SLA tracking.
- **Recommendation:** Audit `_emit_api_event` compatibility shim (likely bypasses patched `_log_event`); refactor to always invoke module-level `log_event`; expand test to assert fallback order.
- **Suggested Tests:** `pytest tests/routers/test_search_logging.py -q`.

### F4. `/system/stats` ignores overrides (P1)
- **Evidence:** Endpoint always uses actual `psutil`; test expecting mocked CPU percent fails (`13.7 == 30.0`). 【1e2e16†L363-L390】【b45c06†L156-L163】
- **Impact:** Cannot simulate or harden system metrics in tests/ops; incorrect telemetry under feature flags.
- **Recommendation:** Prefer FastAPI dependency override (`request.app.dependency_overrides`) or `app.state.psutil` before legacy shim; adjust tests accordingly.
- **Suggested Tests:** `pytest tests/test_system.py::test_system_stats_endpoint_uses_psutil -q`.

### F5. Spotify status caching hides config changes (P1)
- **Evidence:** Cache middleware default pattern caches all `/spotify/**`; status endpoint continues to report `pro_available=True` after credentials cleared, causing 503 tests to fail. 【5742eb†L610-L615】【b45c06†L149-L167】
- **Impact:** Operators cannot rely on `/spotify/status` during credential rotation; clients receive stale availability info.
- **Recommendation:** Exclude status routes from cache rules or force cache invalidation when credential settings change; add regression test covering credential removal.
- **Suggested Tests:** `pytest tests/test_spotify_mode_gate.py::test_spotify_pro_features_require_credentials -q`.

### F6. Playlist cache invalidation ineffective (P1)
- **Evidence:** Playlist sync tests expect updated names/ETags but responses stay stale (`304` vs `200`, names unchanged). 【b45c06†L168-L176】【c08376†L152-L230】
- **Impact:** Clients keep outdated playlist metadata, breaking cache freshness guarantees.
- **Recommendation:** Ensure `PlaylistSyncWorker` writes deterministic `updated_at` values (e.g. monotonic clock or versioning) and verify cache invalidator executes in same loop; extend tests to assert new ETags and body payload.
- **Suggested Tests:** `pytest tests/spotify/test_playlist_cache_invalidation.py::test_playlist_list_busts_cache_on_update_response -q` and `pytest tests/test_spotify.py::test_playlist_sync_worker_persists_playlists -q`.

### F7. Admin fixture mutates global OpenAPI state (P1)
- **Evidence:** Autouse fixture sets `FEATURE_ADMIN_API=1`, registers routes, and never restores env flag—OpenAPI snapshot diverges when suite continues. 【e48f80†L48-L79】【b45c06†L137-L171】
- **Impact:** Snapshot test fails in full runs; other modules unexpectedly expose admin routes.
- **Recommendation:** Reset env vars and unregister routers in fixture teardown (or isolate app per module); add guard ensuring OpenAPI schema resets between tests.
- **Suggested Tests:** Full `pytest` run plus `tests/snapshots/test_openapi_schema.py`.

### F8. Ruff import rule drift (P2)
- **Evidence:** `ruff check --select I` flags dozens of backend modules. 【8bf225†L1-L20】
- **Impact:** Inconsistent import ordering increases merge noise and hides functional diffs.
- **Recommendation:** Run Ruff format/import fixes with repo config, commit formatting, and add CI gate.
- **Suggested Tests:** `ruff format --check .` und `ruff check --select I .` in CI.

### F9. Missing static security analyser (P2)
- **Evidence:** The configured security scan command fails (`command not found`). 【2a7069†L1-L1】
- **Impact:** Security gate is silently skipped; potential vulnerabilities go unnoticed.
- **Recommendation:** Add a vetted security scanner to `requirements-dev.txt`, wire it into CI, and document usage.
- **Suggested Tests:** Execute the configured security scan as part of the quality suite once the tool is installed.

## Next Steps
1. **Schema Fix:** Prioritise migration for `activity_events` (F1) before any admin/API work.
2. **Observability Restoration:** Address telemetry regressions (F2–F3) to regain monitoring coverage.
3. **Runtime Config Corrections:** Fix `/system/stats`, Spotify caching, and playlist invalidation (F4–F6) to stabilise feature flows.
4. **Test Hygiene:** Patch admin fixtures and stabilise OpenAPI snapshot (F7) to unblock full test runs.
5. **Quality Gates:** Re-enable style/security tooling (F8–F9) and enforce in CI.
