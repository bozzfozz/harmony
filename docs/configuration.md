# Configuration Reference

Harmony reads configuration from environment variables with precedence
`environment > .env file > built-in defaults`. Secrets (API keys, Spotify credentials)
should be injected through the environment or a secret manager—never committed to the
repository.

The unified container bundles the backend, workers and the web UI. All variables below
apply to the single service; optional features are disabled by default.

## Core Runtime

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/harmony.db` | `sqlite+aiosqlite:///data/harmony.db` | SQLite is the only supported database. |
| `APP_PORT` | `8080` | `8080` | Single exposed port for API and UI; container binds to `0.0.0.0`. |
| `APP_MODULE` | `app.main:app` | `app.main:app` | ASGI application entrypoint. |
| `UVICORN_EXTRA_ARGS` | _(empty)_ | `--log-level debug` | Additional flags for the embedded Uvicorn server. |
| `DB_RESET` | `0` | `1` | Recreates the SQLite file on start when set to `1`. |
| `APP_ENV` | `dev` | `prod` | High-level environment tag exposed in logs. |
| `ENVIRONMENT` | `dev` | `prod` | Backwards-compatible alias for `APP_ENV`. |
| `HARMONY_PROFILE` | `default` | `unified` | Profile name written into diagnostics. |
| `HARMONY_LOG_LEVEL` | `INFO` | `DEBUG` | Global logging level. |
| `API_BASE_PATH` | `/api/v1` | `/api/v1` | Prefix for public API routes. |
| `REQUEST_ID_HEADER` | `X-Request-ID` | `X-Correlation-ID` | Header name used to inject request IDs. |
| `SMOKE_PATH` | `/live` | `/live` | Path used by smoke tests and entrypoint checks. |
| `PUBLIC_BACKEND_URL` | _(empty)_ | `http://localhost:8080` | Base URL that the frontend uses for API calls. |
| `PUBLIC_FEATURE_FLAGS` | `{}` | `{"beta": true}` | JSON string consumed by the frontend. |
| `PUBLIC_SENTRY_DSN` | _(empty)_ | `https://example@o0.ingest.sentry.io/1` | Optional DSN forwarded to the web UI. |
| `DOWNLOADS_DIR` | `/data/downloads` | `/data/downloads` | Temporary workspace for HDM downloads; must be writable. |
| `MUSIC_DIR` | `/data/music` | `/data/music` | Final destination for tagged tracks; must be writable. |
| `ARTWORK_DIR` | `./artwork` | `/data/artwork` | Storage for downloaded artwork when the feature is enabled. |

## Identity & Security

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `FEATURE_UNIFIED_ERROR_FORMAT` | `true` | `true` | Enables the `{ "ok": false, "error": {…} }` envelope. |
| `ERRORS_DEBUG_DETAILS` | `false` | `true` | Adds debug IDs and hints to error responses (use only in secure environments). |
| `FEATURE_REQUIRE_AUTH` | `false` | `true` | Enforces API-key authentication for non-allowlisted routes. |
| `FEATURE_RATE_LIMITING` | `false` | `true` | Enables the global rate limiting middleware. |
| `FEATURE_ENABLE_LEGACY_ROUTES` | `false` | `true` | Restores archived legacy endpoints. |
| `FEATURE_ADMIN_API` | `false` | `true` | Exposes `/admin/*` artist operations. |
| `HARMONY_API_KEYS` | _(empty)_ | `key1,key2` | Comma-separated API keys accepted by the gateway. |
| `HARMONY_API_KEYS_FILE` | _(empty)_ | `/run/secrets/harmony_keys` | File with one API key per line; merged with `HARMONY_API_KEYS`. |
| `HARMONY_DISABLE_WORKERS` | `false` | `true` | Hard-disables background workers at startup. |
| `WORKERS_ENABLED` | `true` | `false` | Preferred flag controlling worker startup. |
| `WORKER_VISIBILITY_TIMEOUT_S` | _(empty)_ | `60` | Overrides default visibility timeout for queue leases. |
| `AUTH_ALLOWLIST` | automatic | `docs,openapi.json` | Additional path prefixes that bypass authentication. |
| `ALLOWED_ORIGINS` | _(empty)_ | `http://localhost:8080` | CORS allowlist for browser clients. |
| `CORS_ALLOWED_ORIGINS` | _(empty)_ | `http://localhost:8080` | Legacy alias for allowed origins. |
| `CORS_ALLOWED_HEADERS` | `*` | `Content-Type,X-API-Key` | Headers accepted during CORS preflights. |
| `CORS_ALLOWED_METHODS` | `GET,POST,PUT,PATCH,DELETE,OPTIONS` | `GET,POST` | Methods accepted during CORS preflights. |

## Observability & Middleware

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `CACHE_ENABLED` | `true` | `false` | Enables HTTP response caching. |
| `CACHE_DEFAULT_TTL_S` | `30` | `10` | Default TTL in seconds. |
| `CACHE_STALE_WHILE_REVALIDATE_S` | `60` | `120` | Stale-while-revalidate window. |
| `CACHE_MAX_ITEMS` | `5000` | `1000` | Max in-memory cache entries. |
| `CACHE_FAIL_OPEN` | `true` | `false` | Serve original response if cache write fails. |
| `CACHE_STRATEGY_ETAG` | `strong` | `weak` | ETag calculation strategy. |
| `CACHE_WRITE_THROUGH` | `true` | `false` | Immediately invalidates dependent cache entries after writes. |
| `CACHE_LOG_EVICTIONS` | `true` | `false` | Emit logs for cache evictions. |
| `CACHEABLE_PATHS` | _(empty)_ | `/artists|60|120` | Per-path cache rules (`path|ttl|stale`). |
| `GZIP_MIN_SIZE` | `1024` | `2048` | Minimum payload size (bytes) before gzip applies. |
| `HEALTH_DB_TIMEOUT_MS` | `500` | `1000` | DB readiness check timeout. |
| `HEALTH_DEP_TIMEOUT_MS` | `800` | `1500` | Dependency probe timeout. |
| `HEALTH_DEPS` | _(empty)_ | `spotify,slskd` | Additional dependency checks surfaced via `/ready`. |
| `HEALTH_READY_REQUIRE_DB` | `true` | `false` | Allow readiness without DB access (mainly for maintenance). |
| `SECRET_VALIDATE_TIMEOUT_MS` | `800` | `1500` | Timeout for runtime secret validation. |
| `SECRET_VALIDATE_MAX_PER_MIN` | `3` | `6` | Rate limit for validation attempts per provider. |

## SQLite & Storage Helpers

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `PUID` | `1000` | `1000` | User ID applied to mounted volumes (entrypoint helper). |
| `PGID` | `1000` | `1000` | Group ID applied to mounted volumes. |
| `UMASK` | `007` | `002` | Filesystem mask enforced by the entrypoint. |

## Spotify & OAuth

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `SPOTIFY_CLIENT_ID` | _(empty)_ | `aaaaaaaaaaaa` | Spotify OAuth client ID. |
| `SPOTIFY_CLIENT_SECRET` | _(empty)_ | `bbbbbbbbbbbb` | Spotify OAuth client secret. |
| `SPOTIFY_REDIRECT_URI` | _(empty)_ | `http://127.0.0.1:8888/callback` | Overrides the default callback URI. |
| `SPOTIFY_SCOPE` | `user-library-read playlist-read-private playlist-read-collaborative` | `user-library-read` | OAuth scopes requested during authorization. |
| `SPOTIFY_TIMEOUT_MS` | `15000` | `20000` | Timeout for Spotify API calls. |
| `FREE_IMPORT_MAX_LINES` | `200` | `500` | Max lines parsed from text input during free import. |
| `FREE_IMPORT_MAX_FILE_BYTES` | `1048576` | `2097152` | Max upload size for free import files. |
| `FREE_IMPORT_MAX_PLAYLIST_LINKS` | `1000` | `200` | Max playlist links accepted per request. |
| `FREE_IMPORT_HARD_CAP_MULTIPLIER` | `10` | `5` | Hard safety multiplier for playlist expansion. |
| `FREE_ACCEPT_USER_URLS` | `false` | `true` | Allow arbitrary user-submitted URLs in free mode. |
| `FREE_BATCH_SIZE` | `500` | `200` | Batch size for ingest normalization in free mode. |
| `FREE_MAX_PLAYLISTS` | `100` | `50` | Soft cap for playlist submissions per job. |
| `FREE_MAX_TRACKS_PER_REQUEST` | `5000` | `1000` | Hard limit for tracks in a single free ingest request. |
| `BACKFILL_MAX_ITEMS` | `1000` | `2000` | Max items processed per backfill job. |
| `BACKFILL_CACHE_TTL_SEC` | `43200` | `86400` | Cache TTL for backfill lookups. |
| `OAUTH_CALLBACK_PORT` | `8888` | `8888` | Port used by the local OAuth callback helper. |
| `OAUTH_MANUAL_CALLBACK_ENABLE` | `true` | `false` | Allow manual completion via `/api/v1/oauth/manual`. |
| `OAUTH_SESSION_TTL_MIN` | `10` | `20` | Lifetime of OAuth states (minutes). |
| `OAUTH_PUBLIC_HOST_HINT` | _(empty)_ | `https://harmony.example.com` | Hint shown in the OAuth UI for remote callbacks. |
| `OAUTH_SPLIT_MODE` | `false` | `true` | Enables filesystem-based state sharing for split deployments. |
| `OAUTH_STATE_DIR` | `/data/runtime/oauth_state` | `/data/runtime/oauth_state` | Directory for OAuth state files (must be shared in split mode). |
| `OAUTH_STATE_TTL_SEC` | `600` | `900` | TTL of persisted OAuth state files (seconds). |
| `OAUTH_STORE_HASH_CV` | `true` | `false` | Hash the PKCE code verifier before persisting (must be `false` in split mode). |
| `OAUTH_PUBLIC_BASE` | `/api/v1/oauth` | `/api/v1/oauth` | Public base path exposed by the API router. |

## Integrations

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `INTEGRATIONS_ENABLED` | `spotify,slskd` | `spotify,slskd` | Comma-separated list of active providers. |
| `SLSKD_BASE_URL` | `http://localhost:5030` | `http://slskd.local:5030` | Preferred configuration for the slskd daemon. If set, readiness derives connectivity from this value. |
| `SLSKD_URL` | _(legacy)_ | `http://slskd.local:5030` | Legacy alias for `SLSKD_BASE_URL`; supported for backwards compatibility. |
| `SLSKD_HOST` | _(legacy)_ | `slskd.local` | Legacy host override. Provide both host and port when the base URL is not available. |
| `SLSKD_PORT` | _(legacy)_ | `5030` | Legacy port override used together with `SLSKD_HOST`. |
| `SLSKD_API_KEY` | _(empty)_ | `slskd-secret` | API key for slskd. |
| `SLSKD_TIMEOUT_MS` | `8000` | `12000` | Timeout for slskd HTTP calls. |
| `SLSKD_RETRY_MAX` | `3` | `5` | Retry attempts for slskd requests. |
| `SLSKD_RETRY_BACKOFF_BASE_MS` | `250` | `500` | Base backoff delay for retries (milliseconds). |
| `SLSKD_JITTER_PCT` | `20` | `30` | Percent jitter applied to slskd backoff. |
| `SLSKD_PREFERRED_FORMATS` | _(empty)_ | `FLAC,ALAC` | Format preference order for downloads. |
| `SLSKD_MAX_RESULTS` | `200` | `100` | Max search results returned by slskd queries. |
| `MUSIXMATCH_API_KEY` | _(empty)_ | `mm-secret` | Optional Musixmatch API key for lyrics fallback. |

## External Call Defaults

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `EXTERNAL_TIMEOUT_MS` | `15000` | `10000` | Base timeout for provider requests without specific overrides. |
| `EXTERNAL_RETRY_MAX` | `3` | `5` | Retry attempts for generic external calls. |
| `EXTERNAL_BACKOFF_BASE_MS` | `250` | `500` | Base delay for external retry backoff. |
| `EXTERNAL_JITTER_PCT` | `20` | `30` | Percent jitter for external retry backoff. |
| `PROVIDER_MAX_CONCURRENCY` | `10` | `4` | Maximum concurrent provider requests. |

## Artwork & Lyrics

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `ENABLE_ARTWORK` | `false` | `true` | Enables artwork download worker and API routes. |
| `ARTWORK_TIMEOUT_SEC` | `15.0` | `20.0` | Timeout for primary artwork fetch. |
| `ARTWORK_HTTP_TIMEOUT` | `15.0` | `20.0` | HTTP timeout applied to artwork requests. |
| `ARTWORK_MAX_BYTES` | `10485760` | `5242880` | Maximum download size for artwork responses. |
| `ARTWORK_CONCURRENCY` | `2` | `4` | Parallel artwork fetchers for API-triggered requests. |
| `ARTWORK_WORKER_CONCURRENCY` | `2` | `4` | Parallelism for the artwork worker. |
| `ARTWORK_MIN_EDGE` | `1000` | `1500` | Minimum resolution edge length required for artwork. |
| `ARTWORK_MIN_BYTES` | `150000` | `200000` | Minimum payload size to accept. |
| `ARTWORK_FALLBACK_ENABLED` | `false` | `true` | Enable fallback provider when primary fails. |
| `ARTWORK_FALLBACK_PROVIDER` | `musicbrainz` | `fanart` | Name of the fallback provider. |
| `ARTWORK_FALLBACK_TIMEOUT_SEC` | `12.0` | `20.0` | Timeout for fallback fetch. |
| `ARTWORK_FALLBACK_MAX_BYTES` | `10485760` | `5242880` | Max payload for fallback provider. |
| `ARTWORK_POST_PROCESSING_ENABLED` | `false` | `true` | Run additional post-processing commands. |
| `ARTWORK_POST_PROCESSORS` | _(empty)_ | `jpegoptim -m85` | Commands to execute during post-processing. |
| `ENABLE_LYRICS` | `false` | `true` | Enables the automatic lyrics worker. |

## Ingest & Matching

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `INGEST_BATCH_SIZE` | `500` | `200` | Batch size for ingest queue submissions. |
| `INGEST_MAX_PENDING_JOBS` | `2000` | `500` | Queue backlog limit before new jobs are rejected. |
| `FEATURE_MATCHING_EDITION_AWARE` | `true` | `false` | Toggle edition-aware matching heuristics. |
| `MATCH_FUZZY_MAX_CANDIDATES` | `50` | `100` | Candidates considered during fuzzy matching. |
| `MATCH_MIN_ARTIST_SIM` | `0.6` | `0.7` | Minimum similarity threshold for artist names. |
| `MATCH_COMPLETE_THRESHOLD` | `0.9` | `0.95` | Confidence threshold for "complete" discography state. |
| `MATCH_NEARLY_THRESHOLD` | `0.8` | `0.85` | Confidence threshold for "nearly complete" state. |
| `MATCHING_WORKER_BATCH_SIZE` | `5` | `10` | Matching jobs processed per worker iteration. |
| `MATCHING_CONFIDENCE_THRESHOLD` | `0.65` | `0.75` | Minimum score to accept a candidate. |
| `SEARCH_MAX_LIMIT` | `100` | `50` | Max results returned by the search endpoint. |

## Retry & Rate Limiting

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `RETRY_MAX_ATTEMPTS` | `10` | `5` | Default retry attempts for orchestrator tasks. |
| `RETRY_BASE_SECONDS` | `60.0` | `30.0` | Base delay (seconds) between retries. |
| `RETRY_JITTER_PCT` | `0.2` | `0.3` | Fractional jitter for retry delays. |
| `RETRY_SCAN_BATCH_LIMIT` | `25` | `50` | Number of queued retries scanned per sweep. |
| `RETRY_SCAN_INTERVAL_SEC` | `180` | `120` | Interval between retry scans. |
| `RETRY_ARTIST_SYNC_MAX_ATTEMPTS` | `10` | `6` | Max retries for artist sync jobs. |
| `RETRY_ARTIST_SYNC_BASE_SECONDS` | `60` | `120` | Base delay for artist sync retries. |
| `RETRY_ARTIST_SYNC_JITTER_PCT` | `0.2` | `0.4` | Jitter fraction for artist sync retries. |
| `RETRY_ARTIST_SYNC_TIMEOUT_SECONDS` | _(empty)_ | `900` | Optional timeout for a single artist sync retry cycle. |
| `RATE_LIMIT_BUCKET_CAP` | `60` | `120` | Tokens per minute for the global rate limiter. |
| `RATE_LIMIT_REFILL_PER_SEC` | `1.0` | `0.5` | Token refill rate per second. |

## Watchlist & Orchestrator

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `WATCHLIST_MAX_CONCURRENCY` | _(empty)_ | `3` | Hard limit for parallel watchlist items per tick. |
| `WATCHLIST_CONCURRENCY` | _(empty)_ | `3` | Alias for max concurrency (legacy). |
| `WATCHLIST_MAX_PER_TICK` | _(empty)_ | `20` | Upper bound for enqueued artists per timer tick. |
| `WATCHLIST_TICK_BUDGET_MS` | _(empty)_ | `5000` | Processing budget per timer iteration. |
| `WATCHLIST_RETRY_MAX` | _(empty)_ | `3` | Retry attempts per timer cycle. |
| `WATCHLIST_BACKOFF_MAX_TRIES` | _(empty)_ | `5` | Limit before switching to cooldown handling. |
| `WATCHLIST_BACKOFF_BASE_MS` | _(empty)_ | `250` | Base backoff duration (milliseconds). |
| `WATCHLIST_JITTER_PCT` | _(empty)_ | `0.2` | Fractional jitter for watchlist retries. |
| `WATCHLIST_RETRY_BUDGET_PER_ARTIST` | _(empty)_ | `6` | Total retry budget per artist across cycles. |
| `ARTIST_MAX_RETRY_PER_ARTIST` | _(empty)_ | `6` | Legacy alias for retry budget. |
| `WATCHLIST_SPOTIFY_TIMEOUT_MS` | _(empty)_ | `8000` | Timeout for Spotify lookups. |
| `WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS` | _(empty)_ | `12000` | Timeout for Soulseek searches. |
| `WATCHLIST_SEARCH_TIMEOUT_MS` | _(empty)_ | `12000` | Alias for search timeout. |
| `WATCHLIST_SHUTDOWN_GRACE_MS` | _(empty)_ | `5000` | Graceful shutdown window for the timer. |
| `WATCHLIST_DB_IO_MODE` | _(empty)_ | `thread` | Toggle between thread offloading and async DAO. |
| `WATCHLIST_COOLDOWN_MINUTES` | _(empty)_ | `15` | Cooldown duration applied after retries are exhausted. |
| `ARTIST_COOLDOWN_S` | _(empty)_ | `900` | Alias for cooldown duration. |
| `WATCHLIST_INTERVAL` | _(empty)_ | `86400` | Interval between full watchlist scans (seconds). |
| `WATCHLIST_TIMER_ENABLED` | `true` | `false` | Enables the periodic watchlist timer. |
| `WATCHLIST_TIMER_INTERVAL_S` | `900.0` | `86400` | Interval (seconds) between timer executions. |
| `ORCH_GLOBAL_CONCURRENCY` | `20` | `10` | Max concurrent jobs across the orchestrator. |
| `ORCH_HEARTBEAT_S` | `5` | `10` | Interval for lease heartbeats (seconds). |
| `ORCH_POLL_INTERVAL_MS` | `200` | `500` | Base polling interval for the job queue. |
| `ORCH_POLL_INTERVAL_MAX_MS` | `5000` | `1000` | Maximum polling interval when idle. |
| `ORCH_VISIBILITY_TIMEOUT_S` | `30` | `60` | Default lease visibility timeout. |
| `ORCH_POOL_SYNC` | `5` | `10` | Worker pool size for artist sync jobs. |
| `ORCH_POOL_MATCHING` | `5` | `10` | Worker pool size for matching jobs. |
| `ORCH_POOL_RETRY` | `5` | `10` | Worker pool size for retry jobs. |
| `ORCH_POOL_ARTIST_REFRESH` | `5` | `10` | Worker pool size for artist refresh jobs. |
| `ORCH_POOL_ARTIST_DELTA` | `5` | `10` | Worker pool size for delta calculations. |
| `ORCH_PRIORITY_JSON` | _(empty)_ | `{ "artist_sync": 50 }` | JSON overrides for queue priorities. |
| `ORCH_PRIORITY_CSV` | _(empty)_ | `artist_sync:50` | CSV override for queue priorities. |
| `ARTIST_PRIORITY` | _(empty)_ | `artist_sync:50` | Alias for shared priority overrides. |
| `ARTIST_POOL_CONCURRENCY` | _(empty)_ | `4` | Overrides concurrency for artist pipelines. |

## Artist Sync & Metadata

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `ARTIST_SYNC_PRUNE` | `false` | `true` | Soft delete releases missing from provider data. |
| `ARTIST_SYNC_HARD_DELETE` | `false` | `true` | Permanently delete removed releases (irreversible). |
| `ARTIST_SYNC_PRIORITY_DECAY` | `0` | `5` | Priority reduction applied after successful syncs. |
| `ARTIST_STALENESS_MAX_MIN` | `50` | `120` | Maximum staleness (minutes) before warning logs appear. |
| `ARTIST_RETRY_BUDGET_MAX` | `6` | `10` | Retry budget before hard cooldown applies. |
| `SYNC_WORKER_CONCURRENCY` | _(empty)_ | `4` | Concurrency for the download sync worker. |

## Miscellaneous

| Variable | Default | Example | Notes |
| --- | --- | --- | --- |
| `APP_PORT` aliases | _(n/a)_ | `PORT=8080` | Legacy aliases (`PORT`, `UVICORN_PORT`, `SERVICE_PORT`, `WEB_PORT`, `FRONTEND_PORT`) are auto-normalised to `APP_PORT`. |
| `APP_ENV` flags | _(n/a)_ | `PYTEST_CURRENT_TEST` | `PYTEST_CURRENT_TEST` is auto-set by pytest to signal test mode. |
| `SMOKE_PATH` | `/live` | `/live` | Used by smoke scripts; keep aligned with `/live`. |

Refer to [`app/config.py`](../app/config.py) for the authoritative defaults and type
validation logic. Any variable not set falls back to the values shown above or the code
defaults documented in the loader.
