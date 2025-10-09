# Testing Overview

## Lifespan & Worker Lifecycle

The FastAPI lifespan hook orchestrates worker start-up and shutdown. To verify
the wiring without spawning the production workers, the test-suite installs a
lightweight orchestrator harness in `tests/conftest.py` that records scheduler
and dispatcher activity while patching media workers with async no-ops. Enable
the suite with the `lifespan_workers` marker, which flips
`HARMONY_DISABLE_WORKERS` to `0` and activates the fake orchestrator wiring.

Key scenarios covered in `tests/test_lifespan_workers.py`:

- Successful start/stop sequences with log assertions.
- Start-up failures bubbling out of the lifespan entrypoint and subsequent
  manual cleanup.
- Idempotent start/stop cycles (back-to-back lifespan contexts and repeated
  shutdown invocations).
- Cooperative cancellation of long-running tasks within the stop grace period.
- Simulated start timeouts via `asyncio.wait_for` as well as background task
  crashes reported through structured logs.

Helper utilities live in `tests/support/async_utils.py`, providing polling and safe
task cancellation primitives that keep the tests deterministic. The recording
dispatcher collects processed jobs so tests can assert structured outcomes
even though the production logging setup reconfigures handlers during the
FastAPI lifespan startup.

## PostgreSQL test matrix

- Der Marker `@pytest.mark.postgres` kennzeichnet Tests, die explizit gegen
  PostgreSQL laufen und Dialekt-Parität sicherstellen (Queue-Idempotenz,
  Orchestrator-Leases/Heartbeats, Activity-Historie, Async-DAO und der Alembic
  Roundtrip). Die Marker werden von `pytest.ini` registriert und können per
  `pytest -m postgres -q` selektiv ausgeführt werden.
- Im CI übernimmt [`backend-postgres.yml`](../.github/workflows/backend-postgres.yml)
  die Ausführung: `alembic downgrade base || true` → `alembic upgrade head` →
  `pytest -m postgres -q` → `alembic downgrade base`. Der Job nutzt einen PostgreSQL-16-Service mit
  temporären Schemas je Testlauf (`search_path`-Isolation).
- Lokal können dieselben Schritte mit einer Docker-Instanz reproduziert werden.
  Startet zunächst eine Datenbank per `docker compose up -d postgres` und setzt
  anschließend `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/harmony`.
  Die Tests kümmern sich automatisch um Schema-Cleanup
  (`DropSchema(cascade=True)`) und hinterlassen keine Datenbankartefakte.
