# Watchlist Worker

The watchlist worker polls Spotify for new releases of the artists that are
stored in `watchlist_artists` and schedules missing tracks for download via the
SyncWorker. The orchestration is handled by the global Scheduler/Dispatcher
combo: the WatchlistTimer enqueues jobs on its interval, honours orchestrator
stop events and prevents new ticks while shutdown is in progress. The new
implementation is fully async-friendly, time-bounded and supports deterministic
shutdown semantics.

## Execution Flow

1. The worker wakes up on its interval and fetches a batch of artists via the
   `WatchlistDAO`. Artists with a future `last_checked` timestamp are skipped so
   that backoff windows are respected.
2. A per-tick deadline is calculated from `WATCHLIST_TICK_BUDGET_MS`. All work
   must finish before the deadline to avoid starving the event loop.
3. Each artist is processed in a task that is guarded by an
   `asyncio.Semaphore(WATCHLIST_MAX_CONCURRENCY)`.
4. Spotify album/track lookups are wrapped in `asyncio.wait_for` with the
   configured Spotify timeout while the blocking client work is delegated to
   `asyncio.to_thread`. Soulseek searches are similarly wrapped in
   `asyncio.wait_for` using the configured search timeout.
5. Track candidates are deduplicated against already queued downloads. New
   downloads are persisted through the DAO and handed off to the SyncWorker.
6. Failures caused by upstream timeouts or 5xx responses trigger an exponential
   backoff with jitter before the artist is retried. Retries are capped by
   `WATCHLIST_RETRY_MAX` per tick.
7. Sobald das pro-Artist-Retry-Budget erschöpft ist, wird ein persistenter
   Cooldown (`watchlist_artists.retry_block_until`) gesetzt. Der Worker
   überspringt gesperrte Artists, bis der Zeitstempel in der Vergangenheit
   liegt, und löscht den Wert nach einer erfolgreichen Verarbeitung.
7. When the worker stops it waits up to `WATCHLIST_SHUTDOWN_GRACE_MS` and
   cancels any still running tasks so shutdown remains deterministic.

## Configuration

The worker is controlled through the following environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `WATCHLIST_MAX_CONCURRENCY` | `4` | Maximum number of artists processed concurrently per tick. |
| `WATCHLIST_MAX_PER_TICK` | `20` | Maximum number of artists fetched from the database per tick. |
| `WATCHLIST_SPOTIFY_TIMEOUT_MS` | `8_000` | Timeout applied to Spotify artist and album lookups. |
| `WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS` | `12000` | Timeout applied to every Soulseek search. |
| `WATCHLIST_TICK_BUDGET_MS` | `8_000` | Global deadline for a tick. Artists that would exceed the budget are skipped. |
| `WATCHLIST_BACKOFF_BASE_MS` | `250` | Base delay for exponential backoff after dependency failures. |
| `WATCHLIST_RETRY_MAX` | `3` | Maximum number of attempts per artist within a single tick. |
| `WATCHLIST_JITTER_PCT` | `0.2` | Percentage of jitter applied to the calculated backoff delay. |
| `WATCHLIST_SHUTDOWN_GRACE_MS` | `2000` | Grace period before forcefully cancelling the worker task during shutdown. |
| `WATCHLIST_DB_IO_MODE` | `thread` | Database execution mode (`thread` offloads to background threads, `async` expects an async session). |

> **Note:** The legacy `WATCHLIST_INTERVAL` value continues to control how often
> a new tick starts but the work performed during a tick is now limited by the
> budget instead of the interval itself.

## Observability

Structured log lines expose the worker lifecycle:

- `event=watchlist.tick` — tick summary (count, duration, budget, concurrency)
- `event=watchlist.process` — per artist result (`status`, `queued`, `attempts`, `retries`)
- `event=watchlist.cooldown.set` — Retry-Budget ausgeschöpft, Cooldown gesetzt (`minutes`, `retry_block_until`)
- `event=watchlist.cooldown.skip` — Verarbeitung übersprungen, weil der Cooldown noch aktiv ist
- `event=watchlist.cooldown.clear` — Erfolgreicher Lauf hat den Cooldown zurückgesetzt
- `event=watchlist.download` — downloads queued for SyncWorker
- `event=watchlist.search` — Soulseek queries that did not return results

The worker also continues to publish activity and health heartbeats via the
structured logging hooks (`record_worker_started`, `record_worker_stopped`,
`record_worker_heartbeat`).

## Troubleshooting

- **Timeouts:** Increase `WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS` for Soulseek or
  `WATCHLIST_SPOTIFY_TIMEOUT_MS` for Spotify if requests frequently time out,
  but monitor the tick budget as this affects overall runtime.
- **Backoff too aggressive:** Lower `WATCHLIST_BACKOFF_BASE_MS` or reduce the
  retry count if artists remain stuck with future `last_checked` timestamps.
- **Slow shutdowns:** Reduce `WATCHLIST_SHUTDOWN_GRACE_MS` if the process must
  exit faster; ensure dependent services can handle cancellations gracefully.
- **Batch too large:** Tune `WATCHLIST_MAX_PER_TICK` together with the tick
  budget to avoid starvation of other async tasks.
