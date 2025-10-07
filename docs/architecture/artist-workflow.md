# Artist Workflow

The artist workflow keeps persisted artist metadata and release lists in sync with
external providers while coordinating download and matching jobs. The flow spans
multiple subsystems: the watchlist scheduler, orchestrator queues, provider
mocks, and the public API.

```mermaid
graph TD
    Watchlist[(watchlist_artists)]
    Timer[Watchlist timer]
    RefreshQueue[(queue: artist_refresh)]
    ScanQueue[(queue: artist_scan)]
    SyncQueue[(queue: sync)]
    MatchingQueue[(queue: matching)]
    ArtistSyncQueue[(queue: artist_sync)]
    Artists[(artists & artist_releases)]
    Cache[ResponseCache]

    Watchlist -->|load due artists| Timer
    Timer -->|enqueue| RefreshQueue
    RefreshQueue -->|lease| ArtistRefreshJob[Artist refresh handler]
    ArtistRefreshJob -->|enqueue delta| ScanQueue
    ArtistRefreshJob -->|update cooldown| Watchlist
    ScanQueue -->|lease| ArtistScanJob[Artist scan handler]
    ArtistScanJob -->|Soulseek downloads| SyncQueue
    ArtistScanJob -->|mark success / retry| Watchlist
    SyncQueue --> SyncJob[Sync handler]
    SyncJob --> MatchingQueue
    MatchingQueue --> MatchingJob[Matching handler]
    AdminAPI[POST /api/v1/artists/{key}/enqueue-sync] --> ArtistSyncQueue
    ArtistSyncQueue --> ArtistSyncJob[Artist sync handler]
    ArtistSyncJob --> Artists
    ArtistSyncJob -->|invalidate| Cache
    API[GET /api/v1/artists/{key}] --> Cache --> Artists
```

## Lifecycle

1. **Watchlist scheduling** – the watchlist timer loads due entries from the
   `watchlist_artists` table ordered by `last_checked`. Each candidate is enqueued
   on `queue:artist_refresh` with an idempotency key derived from the
   `artist_id` and cutoff timestamp.
2. **Artist refresh** – `artist_refresh` jobs enforce the per-artist retry
   budget, skip paused entries and enqueue `artist_scan` jobs. On success the
   watchlist entry receives updated `last_checked`, `last_scan_at` and optional
   cooldown metadata.
3. **Artist scan / delta** – the scan handler contacts Spotify (album & track
   listings) and Soulseek (download candidates). New candidates create download
   jobs in `queue:sync`; the DAO persists known releases for subsequent runs and
   resets the retry budget. Provider failures raise `WatchlistProcessingError`
   with retry hints so the dispatcher can reschedule with exponential backoff.
4. **Sync & matching** – download jobs transition to the matching queue after
   the stubbed `SyncWorker` acknowledges the work. Matching persists candidate
   matches and completes the download lifecycle.
5. **Artist sync** – the public API `POST /api/v1/artists/{key}/enqueue-sync`
   schedules `artist_sync` jobs. The handler aggregates fresh provider data via
   the `ArtistGateway`, applies deltas against the SQL tables (`artists`,
   `artist_releases`), writes audits and invalidates cached responses.
6. **API read** – cached GET requests for `/api/v1/artists/{key}` serve the
   newest release list once the cache eviction completes. The next read rebuilds
   the cache entry with an updated ETag.

## Error handling & retries

- **Provider timeouts/rate limits** bubble up as `ProviderGatewayTimeoutError`
  or `ProviderGatewayRateLimitedError`. The dispatcher retries according to the
  `RetryPolicyProvider` (configurable via `RETRY_ARTIST_SYNC_*`). Exceeding the
  attempt budget moves the job to the DLQ with `stop_reason='max_retries_exhausted'`.
- **Watchlist processing failures** (Spotify/Soulseek errors) raise
  `WatchlistProcessingError`. Retryable errors are requeued with jittered
  backoff; non-retryable errors dead-letter immediately.
- **Lease loss** – orchestrator heartbeats ensure long-running jobs keep their
  leases. If the lease cannot be renewed the dispatcher aborts execution and
  requeues the job.

## Idempotency & deduplication

- **Watchlist timer** – each enqueue uses
  `idempotency_key=f"artist-refresh:{artist_id}:{cutoff}"`, preventing duplicate
  refresh jobs for the same scan window.
- **Artist scan** – download submissions include
  `idempotency_key=f"watchlist-download:{download_id}"`, so repeated scans do not
  emit duplicate sync jobs.
- **Artist sync** – `enqueue_artist_sync` hashes the payload (artist key &
  force flag) to detect already queued jobs. The API reports
  `already_enqueued=true` when a duplicate request arrives.

## Cache invalidation

`ArtistSyncHandlerDeps.response_cache` is wired to the FastAPI
`ResponseCache`. Successful artist syncs call `bust_artist_cache`, which evicts
all cached variants (strong ETag + auth variant) for the detail route. Subsequent
API reads observe a new ETag and updated payload.

## Logging & observability

- **Structured logs** – all handlers emit `worker.job` events for enqueue,
  success, retries and DLQ transitions. The dispatcher produces
  `orchestrator.dispatch` and `orchestrator.commit` events for each lease.
- **API boundary** – `api.request` logs capture the enqueue and read requests.
- **Metrics counters** – `orchestrator_events` increment Prometheus metrics for
  scan/refresh outcomes, retry exhaustion and timer activity.

## Failure scenarios

- **Provider outage** – repeated provider timeouts eventually exhaust the retry
  budget. The job is dead-lettered and the watchlist entry retains its previous
  state; operators can inspect the DLQ via the existing `/dlq` endpoints.
- **Duplicate enqueue** – calling the enqueue endpoint twice returns the existing
  queue job without scheduling another run, ensuring the downstream pipeline
  remains idempotent.
- **Cache drift** – if cache invalidation fails the handler records a cache
  eviction count of `0` in the job result, making the condition observable in
  logs and tests.

