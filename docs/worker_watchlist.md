# Watchlist Worker

The watchlist worker polls Spotify for new releases of the artists that are
stored in `watchlist_artists` and schedules missing tracks for download via the
SyncWorker. The new implementation is fully async-friendly, time-bounded and
supports deterministic shutdown semantics.

## Execution Flow

1. The worker wakes up on its interval and fetches a batch of artists via the
   `WatchlistDAO`. Artists with a future `last_checked` timestamp are skipped so
   that backoff windows are respected.
2. A per-tick deadline is calculated from `WATCHLIST_TICK_BUDGET_MS`. All work
   must finish before the deadline to avoid starving the event loop.
3. Each artist is processed in a task that is guarded by an
   `asyncio.Semaphore(WATCHLIST_CONCURRENCY)`.
4. Spotify album/track lookups use `asyncio.to_thread` to offload the blocking
   client. Soulseek searches are wrapped in `asyncio.wait_for` using the
   configured search timeout.
5. Track candidates are deduplicated against already queued downloads. New
   downloads are persisted through the DAO and handed off to the SyncWorker.
6. Failures caused by upstream timeouts or 5xx responses trigger an exponential
   backoff with jitter before the artist is retried.
7. When the worker stops it waits up to `WATCHLIST_SHUTDOWN_GRACE_MS` and
   cancels any still running tasks so shutdown remains deterministic.

## Configuration

The worker is controlled through the following environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `WATCHLIST_CONCURRENCY` | `4` | Maximum number of artists processed concurrently per tick. |
| `WATCHLIST_MAX_PER_TICK` | `20` | Maximum number of artists fetched from the database per tick. |
| `WATCHLIST_SEARCH_TIMEOUT_MS` | `1200` | Timeout applied to every Soulseek search. |
| `WATCHLIST_TICK_BUDGET_MS` | `8000` | Global deadline for a tick. Artists that would exceed the budget are skipped. |
| `WATCHLIST_BACKOFF_BASE_MS` | `500` | Base delay for exponential backoff after dependency failures. |
| `WATCHLIST_BACKOFF_MAX_TRIES` | `3` | Maximum number of attempts per artist within a single tick. |
| `WATCHLIST_JITTER_PCT` | `0.2` | Percentage of jitter applied to the calculated backoff delay. |
| `WATCHLIST_SHUTDOWN_GRACE_MS` | `2000` | Grace period before forcefully cancelling the worker task during shutdown. |

> **Note:** The legacy `WATCHLIST_INTERVAL` value continues to control how often
a new tick starts but the work performed during a tick is now limited by the
budget instead of the interval itself.

## Observability

Structured log lines expose the worker lifecycle:

- `event=watchlist.tick` — tick summary (count, duration, budget, concurrency)
- `event=watchlist.task` — per artist result (`status`, `queued`, `attempts`)
- `event=watchlist.download` — downloads queued for SyncWorker
- `event=watchlist.search` — Soulseek queries that did not return results

The worker also continues to publish activity and health heartbeats via the
existing metrics hooks (`record_worker_started`, `record_worker_stopped`,
`record_worker_heartbeat`).

## Troubleshooting

- **Timeouts:** Increase `WATCHLIST_SEARCH_TIMEOUT_MS` if Soulseek frequently
  times out, but monitor the tick budget as this affects overall runtime.
- **Backoff too aggressive:** Lower `WATCHLIST_BACKOFF_BASE_MS` or reduce the
  retry count if artists remain stuck with future `last_checked` timestamps.
- **Slow shutdowns:** Reduce `WATCHLIST_SHUTDOWN_GRACE_MS` if the process must
  exit faster; ensure dependent services can handle cancellations gracefully.
- **Batch too large:** Tune `WATCHLIST_MAX_PER_TICK` together with the tick
  budget to avoid starvation of other async tasks.
