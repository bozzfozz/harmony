# Testing Overview

## Lifespan & Worker Lifecycle

The FastAPI lifespan hook orchestrates worker start-up and shutdown. To verify
the wiring without spawning the production workers, the test-suite provides a
stub registry (`tests/fixtures/worker_stubs.py`) that records every lifecycle
call and logs synthetic `event=worker.*` entries. Enable the suite with the
`lifespan_workers` marker, which flips `HARMONY_DISABLE_WORKERS` to `0` and
activates the fake worker wiring.

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
task cancellation primitives that keep the tests deterministic. The worker stub
registry exposes `log_events` so tests can assert structured log metadata
(`event`, `status`, `duration_ms`) even though the production logging setup
reconfigures handlers during the FastAPI lifespan startup.
