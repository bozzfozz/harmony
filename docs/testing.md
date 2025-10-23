# Testing Overview

The streamlined test-suite focuses on verifying the SQLite bootstrap flow and the
operational guards that keep Harmony healthy. All tests run against SQLite and
avoid external services so the suite stays fast and deterministic.

## Database bootstrap

- `tests/test_db_bootstrap.py` covers `app.db.init_db()` creating a brand-new
  schema on empty files as well as idempotent re-runs.
- `tests/test_config_database.py` exercises the configuration defaults for
  `DATABASE_URL` across environments (`dev`, `prod`, `test`).
- `tests/test_ready_check.py` validates that the self-check logic reports the
  correct mode (`file` vs. `memory`) and probes directory permissions for the
  configured SQLite database file.

These tests rely on temporary directories or `:memory:` URLs and can therefore
run in parallel without coordinating shared state. Helper functions
`reset_engine_for_tests()` and `init_db()` ensure a pristine engine for every
scenario.

## Operational checks

- Startup guards (triggered via `/api/health/ready` or `python -m app.ops.selfcheck --assert-startup`) use `app.ops.selfcheck.aggregate_ready()` to validate
  environment variables, directories and database reachability. Dedicated tests
  assert the behaviour of these checks across failure modes (missing env, bad
  DSNs, unwritable directories).
- The readiness endpoint is powered by `app.services.health.HealthService`.
  Unit tests confirm that dependency probes and database pings are aggregated
  without relying on migrations.

## UI verification

- `tests/ui/` deckt jede veröffentlichte `/ui`-Seite sowie alle Fragmente ab.
  Die Tests prüfen `text/html` Content-Types, rollenbasierte Zugriffe und
  CSRF-Abbrüche wenn Tokens fehlen.
- `scripts/dev/ui_guard.sh` verhindert Platzhalter in Templates, verbietet
  HTMX-Calls auf `/api/...` und stellt sicher, dass die statischen Assets unter
  `app/ui/static/` vorhanden sind.
- `scripts/dev/ui_smoke_local.sh` fährt die App lokal hoch, authentifiziert sich
  per `/ui/login` und ruft `/live`, `/ui` sowie exemplarische Fragmente auf. Der
  Lauf bricht ab, sobald HTML-Antworten Platzhalter enthalten oder nicht als
  `text/html` ausgeliefert werden.

## Running the suite

Run the static type checks before executing tests:

```bash
mypy --config-file mypy.ini
```

Execute the full backend suite locally via:

```bash
pytest -q
```

The same command runs locally without additional services. SQLite is
bootstrapped automatically; set `DB_RESET=1` to force a clean database between
runs when reproducing production-like behaviour.
