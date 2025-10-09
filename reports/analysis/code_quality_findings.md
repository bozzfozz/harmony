# Code Quality Findings — Watchlist & Runtime Configuration

This report captures four actionable follow-up tasks discovered during a targeted review of the watchlist domain, runtime configuration docs, and related tests.

## 1. Fix typo in runtime configuration docs
- **Issue**: The runtime configuration guide misspells „Injizieren“ as „Injezieren“ when describing `VITE_RUNTIME_API_KEY`, which is confusing in German prose.【F:docs/ops/runtime-config.md†L54-L59】
- **Suggested task**: Correct the spelling in `docs/ops/runtime-config.md` to maintain professional documentation quality.

## 2. Normalize artist identifiers in `WatchlistService`
- **Issue**: `_parse_artist_key` returns the raw identifier portion without trimming whitespace. As a result, `spotify:123` and `spotify: 123` are treated as different entries, allowing duplicates despite identical logical IDs.【F:app/services/watchlist_service.py†L325-L357】
- **Suggested task**: Strip surrounding whitespace from the identifier inside `_parse_artist_key` (and add regression coverage) so duplicate watchlist entries cannot be created via spacing tricks.

## 3. Align README watchlist endpoint description
- **Issue**: The README still documents `DELETE /watchlist/{id}`, but the public API expects `artist_key` (e.g. `/watchlist/spotify:artist-42`). This mismatch can mislead API consumers following the docs.【F:README.md†L336-L344】
- **Suggested task**: Update the README to reference `{artist_key}` (and mention the required prefix) for the watchlist deletion endpoint.

## 4. Strengthen watchlist API tests
- **Issue**: Current watchlist tests only cover exact-key duplication; they do not assert normalization for keys containing stray whitespace, leaving the bug above undetected.【F:tests/test_watchlist.py†L18-L40】
- **Suggested task**: Extend `tests/test_watchlist.py` with a case that posts a key containing spaces (e.g. `"spotify: artist-99"`) and verifies the service trims it, preventing duplicates.

