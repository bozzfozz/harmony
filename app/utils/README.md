# Harmony Utility Modules

Dieses Verzeichnis bündelt wiederverwendbare, seiteneffektfreie Helfer, die von
Orchestrator, Integrationen und Services gemeinsam genutzt werden.

## Module

- `retry.py` – Exponentielles Backoff mit Jitter (`exp_backoff_delays`,
  `with_retry`, `RetryDirective`).
- `priority.py` – Parsen von Prioritäts-Maps aus JSON oder CSV.
- `idempotency.py` – Stabile Idempotency Keys (`make_idempotency_key`).
- `time.py` – `now_utc`, `monotonic_ms` und `sleep_jitter_ms`.
- `concurrency.py` – Globale/pool-spezifische Semaphore (`BoundedPools`,
  `acquire_pair`).
- `jsonx.py` – Sichere JSON Serialisierung (`safe_dumps`, `safe_loads`,
  `try_parse_json_or_none`).
- `validate.py` – Primitive Validatoren (`clamp_int`, `require_non_empty`,
  `positive_int`).

## Beispiele

```python
from app.utils.retry import with_retry, RetryDirective

async def call_provider():
    return await client.fetch()

async def safe_call():
    def classify(err: Exception) -> RetryDirective:
        return RetryDirective(retry=isinstance(err, TimeoutError))

    return await with_retry(
        call_provider,
        attempts=3,
        base_ms=250,
        jitter_pct=20,
        timeout_ms=2_000,
        classify_err=classify,
    )
```
