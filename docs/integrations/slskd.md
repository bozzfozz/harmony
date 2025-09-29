# slskd Integration

Harmony communicates with the local [slskd](https://github.com/slskd/slskd) instance via the
internal integration adapter. The adapter issues asynchronous HTTP calls to the
`/api/v0/search/tracks` endpoint, normalises the response into Harmony's `TrackCandidate`
representation and applies consistent error handling. Queries and optional artists are normalised
to strip quotes, Unicode variants and common `(feat.*)` / `(explicit)` markers before reaching the
upstream service.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `SLSKD_BASE_URL` | `http://localhost:5030` | Base URL of the slskd service. Legacy `SLSKD_URL` is still honoured. |
| `SLSKD_API_KEY` | `None` | Optional API key presented via the `X-API-Key` header. |
| `SLSKD_TIMEOUT_MS` | `8000` | Hard timeout for upstream requests in milliseconds. |
| `SLSKD_RETRY_MAX` | `3` | Number of retry attempts on timeouts/5xx/429 responses. |
| `SLSKD_RETRY_BACKOFF_BASE_MS` | `250` | Base value for exponential backoff with ±20 % jitter. |
| `SLSKD_PREFERRED_FORMATS` | `FLAC,ALAC,APE,MP3` | Format preference order used to rank candidates. |
| `SLSKD_MAX_RESULTS` | `50` | Maximum number of candidates returned per request. |

The adapter caps `limit` to the configured `SLSKD_MAX_RESULTS` (and never above 100) to keep payload
sizes predictable. Queries longer than 256 characters or empty strings are rejected with
`VALIDATION_ERROR` before contacting the upstream service.

## Request

```
GET /api/v0/search/tracks?query=<text>&limit=<n>
X-API-Key: <optional secret>
Accept: application/json
```

The adapter trims incoming queries, applies the described normalisation and forwards the resolved
timeout via the shared `httpx.AsyncClient`. Retries honour exponential backoff with jitter for
timeouts, connection errors, 5xx responses and rate limits.

## Normalised Track Schema

The adapter converts the raw JSON payload into `app.integrations.base.TrackCandidate`. The following
fields are populated when available:

- `title`
- `artist`
- `format`
- `bitrate_kbps`
- `size_bytes`
- `seeders`
- `username`
- `availability` (bounded to `[0.0, 1.0]`)
- `source` (`"slskd"`)
- `download_uri` (magnet link or filesystem path when present)
- `metadata` (filename, bitrate mode, score when available)

Entries nested within `results[].files[]` are flattened, enriched with their parent `username` and
sorted by the configured format preferences and seeder count.

## Error Mapping

| Upstream Condition | Adapter Exception | Integration Service Response |
| --- | --- | --- |
| `429 Too Many Requests` | `SlskdAdapterRateLimitedError` | `RATE_LIMITED` with `meta.retry_after_ms` and the original `Retry-After` header when present. |
| `5xx`, network failures, timeouts | `SlskdAdapterDependencyError` | `DEPENDENCY_ERROR` with optional `meta.provider_status`. |
| Invalid/garbled JSON | `SlskdAdapterInternalError` | `INTERNAL_ERROR`. |
| Upstream 4xx validation errors | `SlskdAdapterValidationError` | `VALIDATION_ERROR` with `meta.provider_status`. |
| Local validation (empty query, limit ≤ 0) | – | `VALIDATION_ERROR`. |

When slskd omits `Retry-After`, the adapter supplies a fallback derived from the computed
backoff interval before surfacing the rate limit error.

## Logging

Every slskd lookup emits a structured log with `event="slskd.search"`, including status,
`duration_ms`, `limit`, `results_count` and the upstream status code. Failures log at `WARNING`
level for dependency issues and `ERROR` for malformed payloads.

## Example Response

```json
[
  {
    "title": "Smells Like Teen Spirit",
    "artist": "Nirvana",
    "format": "FLAC",
    "bitrate_kbps": 0,
    "size_bytes": 12345678,
    "seeders": 12,
    "username": "collector",
    "availability": 1.0,
    "source": "slskd",
    "download_uri": "magnet:?xt=urn:btih:abc123",
    "metadata": {
      "filename": "Nirvana - Smells Like Teen Spirit.flac",
      "score": 0.92
    }
  }
]
```

`IntegrationService.search_tracks("slskd", ...)` returns the above structure and raises the mapped
Harmony errors for the listed failure scenarios.
