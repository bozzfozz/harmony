# Harmony Health Audit — QA-AUDIT-001

## Executive Summary (Top Risks)
1. **Watchlist worker blocked the event loop during Spotify lookups** – synchronous Spotipy calls were executed directly inside the async worker loop, risking stalled cancellation, stuck retry intervals, and back-pressure on other background tasks.
2. **Artwork embedding uses `urlopen` without network limits** – the beets artwork path streams arbitrary URLs without socket timeouts or size guards, allowing unbounded hangs or memory pressure when remote hosts misbehave.
3. **Background workers share the same pattern of direct sync client usage** – auto-sync and discography flows mirror the watchlist implementation and should be reviewed to avoid hidden blocking segments.
4. **HTTP endpoints still raise plain `HTTPException` details** – many routers surface string-only `detail` payloads instead of the canonical `{code,message}` error schema, weakening API contract guarantees.
5. **Lifespan orchestration lacks regression tests** – worker start/stop sequencing is complex yet currently untested, so regressions in cancellation paths could slip through CI.

## Detailed Findings
### 1. Watchlist worker event-loop starvation (High)
- **Root cause**: `WatchlistWorker._process_artist` invoked `SpotifyClient` methods synchronously inside `async` code, so every album/track fetch blocked the event loop until Spotipy returned.【F:app/workers/watchlist_worker.py†L116-L166】  
- **Impact**: Slow Spotify responses stalled queue progress, prevented timely cancellation via `stop()`, and introduced cascading delays for Soulseek scheduling.  
- **Fix**: Offload the blocking calls via `asyncio.to_thread`, ensuring the coroutine yields control while Spotipy works.【F:app/workers/watchlist_worker.py†L119-L166】

### 2. Artwork download without safety rails (Medium)
- **Root cause**: `BeetsClient.embed_artwork` streams album art with `urllib.request.urlopen` and no timeout/limit, so hostile endpoints can hold file descriptors indefinitely or deliver multi-GB payloads.【F:app/core/beets_client.py†L186-L212】  
- **Impact**: Worker tasks may hang forever and exhaust memory when fetching artwork from unreliable hosts.  
- **Recommendation**: Inject configurable HTTP timeout and enforce maximum byte budgets before writing to disk.

### 3. Broader worker blocking risk (Medium)
- **Observation**: AutoSync and Discography workers re-use Spotify lookups from async contexts; they likely need the same `asyncio.to_thread` treatment validated for the watchlist flow.【F:app/workers/watchlist_worker.py†L101-L210】  
- **Recommendation**: Audit and refactor these workers to avoid similar starvation scenarios, leveraging the new regression test pattern.

### 4. Error contract drift (Low)
- **Observation**: Routers continue to raise raw `HTTPException(detail=str)` responses instead of the documented `{code,message}` envelope (e.g. `/api/metadata/update`, `/api/soulseek/download/*`).【F:app/routers/metadata_router.py†L33-L64】【F:app/routers/soulseek_router.py†L96-L569】  
- **Recommendation**: Introduce a shared error builder returning canonical codes (`DEPENDENCY_ERROR`, `NOT_FOUND`, etc.) and update OpenAPI schemas accordingly.

### 5. Lifespan orchestration coverage gap (Low)
- **Observation**: Worker lifecycle logic in `app/main.py` coordinates many tasks, yet there are no explicit tests validating cancellation, retries, or double-start behaviour.【F:app/main.py†L95-L214】【F:tests/simple_client.py†L1-L87】  
- **Recommendation**: Add lifespan-focused tests (or scenario harness) to ensure future regressions surface quickly.

## Implemented Fixes
- Offloaded Spotify lookups in the watchlist worker to executor threads and added regression coverage ensuring the async pathway uses `asyncio.to_thread`.【F:app/workers/watchlist_worker.py†L119-L166】【F:tests/test_watchlist.py†L108-L147】

## Follow-up Tasks
- Track follow-up work via `ToDo.md` (blocking API audits and artwork HTTP safeguards recorded under open backend tasks).【F:ToDo.md†L52-L58】
