## TD-20251008-001 Restore activity_events migration
- **Status:** done
- **Priority:** P0
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T12:00:00Z
- **Tags:** db, admin, migration
- **Description:** Admin artist APIs crash because the ORM references an `activity_events` table that has never been created. A blocking schema gap prevents audit, reconcile, and cache invalidation flows from running and causes six admin tests to error. 【F:reports/analysis/backend_deep_scan.md†L23-L29】【b45c06†L137-L176】
- **Acceptance Criteria:**
  - Full admin API suite runs without `no such table` errors.
- **Risks/Impact:** Schema changes in production environments require coordination and rollback planning.
- **Dependencies:** None.
- **Subtasks:**
  - [x] CODX-P0-DB-311 — Author and apply `activity_events` migration with verification harness.

## TD-20251008-002 Restore orchestrator lease telemetry
- **Status:** done
- **Priority:** P1
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T12:05:00Z
- **Tags:** observability, orchestrator, logging
- **Description:** Scheduler leases no longer emit `orchestrator.lease` events, so caplog-based tests and production dashboards miss queue churn signals. 【F:reports/analysis/backend_deep_scan.md†L30-L35】【001fdf†L1-L44】
- **Acceptance Criteria:**
  - `test_scheduler_leases_jobs_in_priority_order` observes expected lease events.
  - Lease logs include `event`, `job_type`, `status`, and `entity_id` fields for every lease attempt.
  - Observability docs updated to reflect log contract.
- **Risks/Impact:** Incorrect logger wiring could spam logs or degrade performance if not throttled.
- **Dependencies:** TD-20251008-001 (shared admin migrations) — ensure logging changes tested after schema fix.
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; `pytest` failure output; Scheduler metrics logger patch. 【F:reports/analysis/backend_deep_scan.md†L30-L35】【001fdf†L1-L44】【F:app/orchestrator/scheduler.py†L1-L180】【F:tests/orchestrator/test_scheduler.py†L1-L120】
- **Subtasks:**
  - [x] CODX-P1-OBS-312 — Audit scheduler logging pipeline and reinstate lease event emission with regression test.

## TD-20251008-003 Fix search router api.request instrumentation
- **Status:** done
- **Priority:** P1
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T12:10:00Z
- **Tags:** observability, router, telemetry
- **Description:** The search endpoint calls `_emit_api_event` but no `api.request` log is emitted, breaking monitoring and failing `test_search_router_emits_api_request_event`. 【F:reports/analysis/backend_deep_scan.md†L36-L40】【001fdf†L79-L117】
- **Acceptance Criteria:**
  - `api.request` events contain component, entity_id, duration, and status for `/search` requests.
  - Compatibility shim honors monkeypatched `log_event` in tests.
  - Documentation updated for search telemetry.
- **Risks/Impact:** Mis-handled logger patching could duplicate events or break other routers.
- **Dependencies:** None.
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; router logging test logs; Search router fallback implementation. 【F:reports/analysis/backend_deep_scan.md†L36-L40】【001fdf†L79-L117】【F:app/api/search.py†L1-L140】【F:tests/routers/test_search_logging.py†L1-L120】
- **Subtasks:**
  - [x] CODX-P1-OBS-313 — Refactor `_emit_api_event` fallback and extend router logging tests.

## TD-20251008-004 Honor psutil overrides in system stats
- **Status:** done
- **Priority:** P1
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T12:15:00Z
- **Tags:** config, diagnostics, api
- **Description:** `_resolve_psutil` always returns the real module, so `/system/stats` cannot be mocked or sandboxed; tests expecting overridden CPU metrics fail. 【F:reports/analysis/backend_deep_scan.md†L42-L46】【1e2e16†L363-L390】
- **Acceptance Criteria:**
  - Endpoint respects FastAPI dependency overrides or `app.state.psutil` injections.
  - Tests can substitute dummy psutil implementations without patching internals.
  - Regression test covers fallback precedence.
- **Risks/Impact:** Incorrect override precedence could break production metrics if real psutil becomes optional.
- **Dependencies:** None.
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; `/system/stats` regression test; Resolver patch. 【F:reports/analysis/backend_deep_scan.md†L42-L46】【b45c06†L156-L163】【F:app/api/system.py†L360-L460】【F:tests/test_system.py†L1-L120】
- **Subtasks:**
  - [x] CODX-P1-CONF-314 — Rework `_resolve_psutil` to honor overrides and add targeted unit tests.

## TD-20251008-005 Decache Spotify status responses on credential changes
- **Status:** done
- **Priority:** P1
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T07:45:00Z
- **Tags:** cache, spotify, api
- **Description:** Cache middleware caches all `/spotify/**` routes, so `/spotify/status` reports stale `pro_available` after credentials are cleared and search endpoints still execute. 【F:reports/analysis/backend_deep_scan.md†L48-L52】【5742eb†L610-L615】
- **Acceptance Criteria:**
  - Status endpoint reflects credential availability immediately after settings change.
  - `test_spotify_pro_features_require_credentials` passes without manually clearing caches.
  - Cache strategy documented for status routes.
- **Risks/Impact:** Disabling caching could increase load on genuine Spotify requests; need targeted scope.
- **Dependencies:** TD-20251008-004 (shared config review) for coordinated middleware changes.
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; spotify gate test failure. 【F:reports/analysis/backend_deep_scan.md†L48-L52】【b45c06†L149-L167】
- **Subtasks:**
  - [x] CODX-P1-SPOT-315 — Adjust cache rules or add busting hook for `/spotify/status` and add regression tests.

## TD-20251008-006 Repair playlist cache invalidation
- **Status:** done
- **Priority:** P1
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T12:20:00Z
- **Tags:** cache, playlists, worker
- **Description:** Playlist sync completes but cached responses retain old names/ETags, so clients receive 304 responses with stale payloads. 【F:reports/analysis/backend_deep_scan.md†L54-L58】【b45c06†L168-L176】
- **Acceptance Criteria:**
  - `/spotify/playlists` and detail endpoints emit new ETags after sync updates.
  - Cache invalidator metrics/logs confirm evictions for updated playlist IDs.
  - Tests `test_playlist_sync_worker_persists_playlists` and `test_playlist_list_busts_cache_on_update_response` pass.
- **Risks/Impact:** Aggressive invalidation could evict unrelated cache entries; ensure key scoping is correct.
- **Dependencies:** TD-20251008-005 (shared cache strategy).
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; spotify playlist test failures; Cache invalidator enhancements. 【F:reports/analysis/backend_deep_scan.md†L54-L58】【b45c06†L168-L176】【F:app/workers/playlist_sync_worker.py†L1-L140】【F:tests/spotify/test_playlist_cache_invalidation.py†L1-L40】
- **Subtasks:**
  - [x] CODX-P1-SPOT-316 — Investigate playlist `updated_at` handling and ensure cache eviction/ETag refresh.

## TD-20251008-007 Stabilise admin fixture OpenAPI state
- **Status:** done
- **Priority:** P1
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T12:25:00Z
- **Tags:** testing, admin, openapi
- **Description:** The autouse admin fixture enables admin routes and leaves them registered, mutating the global FastAPI app and causing OpenAPI snapshot drift. 【F:reports/analysis/backend_deep_scan.md†L60-L64】【e48f80†L48-L79】
- **Acceptance Criteria:**
  - Fixture teardown restores environment variables and unregisters admin routers.
  - `tests/snapshots/test_openapi_schema.py` passes when running the full suite.
  - Documented guidance for isolating admin-enabled tests.
- **Risks/Impact:** Improper route removal might break legitimate admin tests; ensure isolation strategy validated.
- **Dependencies:** TD-20251008-001 (admin schema migration) to ensure consistent test DB state.
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; OpenAPI snapshot failure; Fixture teardown fix. 【F:reports/analysis/backend_deep_scan.md†L60-L64】【b45c06†L137-L171】【F:tests/api/test_admin_artists.py†L1-L220】【F:tests/snapshots/test_openapi_schema.py†L1-L40】
- **Subtasks:**
  - [x] CODX-P1-TEST-317 — Refine admin fixtures to cleanly toggle routes and reset OpenAPI cache.

## TD-20251009-001 Enforce required CI checks post-reset
- **Status:** todo
- **Priority:** P1
- **Scope:** all
- **Owner:** platform
- **Created_at (UTC):** 2025-10-09T16:20:19Z
- **Updated_at (UTC):** 2025-10-09T16:20:19Z
- **Tags:** ci, github-actions, branch-protection
- **Description:** After merging the CI reset, branch protection must mandate the `ci-backend` (required) and `ci-frontend` (conditional) checks so regressions cannot merge without passing the new gates. Settings changes also need documentation in the rule description per governance policy.
- **Acceptance Criteria:**
  - Branch protection on `main` lists `ci-backend` as a required status check.
  - `ci-frontend` is required when the frontend pipeline is active (package manifest present) and documented accordingly.
  - Rule description references `CODX-CI-RESET-001` and links to `REPO_MAINTENANCE.md` for marker guidance.
  - Change log of repository settings stored for audit (screenshot or admin note).
- **Risks/Impact:** Missing required checks would allow non-compliant merges, reintroducing flaky or slow workflows.
- **Dependencies:** CODX-CI-RESET-001 must be merged so the new workflow names exist.
- **References:** CODX-CI-RESET-001; `REPO_MAINTENANCE.md` guidance.
- **Subtasks:**
  - [ ] CODX-CI-RESET-001A — Update branch protection required checks and attach configuration evidence in the operations runbook (`docs/operations/ci.md`).

## TD-20251008-008 Enforce Ruff import sorting
- **Status:** done
- **Priority:** P2
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T09:21:10Z
- **Tags:** tooling, lint, formatting
- **Description:** `ruff check --select I` fails on numerous backend modules, signaling drift from the repo import style baseline. 【F:reports/analysis/backend_deep_scan.md†L66-L70】【8bf225†L1-L20】
- **Acceptance Criteria:**
  - All backend files sort imports per repo configuration (`pyproject.toml`).
  - CI includes Ruff formatting and lint steps (inkl. Importregel) alongside mypy, pytest and pip-audit gates.
  - Developer documentation verweist auf Ruff für Formatierung & Import-Sortierung.
- **Risks/Impact:** Large import reordering may cause merge conflicts; coordinate rollout across branches.
- **Dependencies:** None.
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; `reports/analysis/_evidence/ruff_import_check.txt`. 【F:reports/analysis/backend_deep_scan.md†L66-L70】【F:reports/analysis/_evidence/ruff_import_check.txt†L1-L20】
- **Subtasks:**
  - [x] CODX-P2-TOOL-318 — Apply Ruff import sorting and wire checks into CI.

## TD-20251008-009 Security scanner consolidation
- **Status:** wontdo
- **Priority:** P2
- **Scope:** backend
- **Owner:** codex
- **Created_at (UTC):** 2025-10-08T06:52:42Z
- **Updated_at (UTC):** 2025-10-08T09:45:00Z
- **Tags:** security, tooling
- **Description:** Die geplante Wiederaufnahme des statischen Sicherheitsscans wird durch `CODX-TOOL-702` abgelöst. Das Projekt setzt künftig auf Abhängigkeits-Audits (`pip-audit`) als verpflichtendes Gate und dokumentiert diese Änderung hiermit. 【F:README.md†L453-L461】
- **Acceptance Criteria:**
  - Dokumentation und Policies spiegeln die Entscheidung wider (erledigt durch `CODX-TOOL-702`).
  - CI-Pipeline setzt `pip-audit` als Security-Gate ein.
  - Keine offenen Tasks mehr zur Wiederaufnahme des ursprünglichen Scans.
- **Risks/Impact:** Statisches Code-Scanning entfällt; mögliche Schwachstellen werden ausschließlich über Dependency-Audits entdeckt.
- **Dependencies:** TD-20251008-008 (align tooling updates).
- **References:** CODX-P0-ANLY-500; `reports/analysis/backend_deep_scan.md`; TASK `CODX-TOOL-702`.
- **Subtasks:**
  - [ ] CODX-P1-SEC-401 — Überarbeiten oder ersetzen: statisches Sicherheitsscanning wird aktuell nicht weiterverfolgt.
