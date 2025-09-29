# slskd Integration

Harmony communicates with the local [slskd](https://github.com/slskd/slskd) instance via the
internal integration adapter. The adapter issues asynchronous HTTP calls to the
`/api/v0/search/tracks` endpoint, normalises the response into Harmony's generic track schema and
applies consistent error handling.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `SLSKD_URL` | `http://localhost:5030` | Base URL of the slskd service. |
| `SLSKD_API_KEY` | `None` | Optional API key presented via the `X-API-Key` header. |
| `SLSKD_TIMEOUT_MS` | `1200` | Hard timeout for upstream requests in milliseconds. |
| `SLSKD_RATE_LIMIT_RETRY_AFTER_FALLBACK_MS` | `2000` | Fallback retry-after hint used when slskd omits the header. |

The adapter caps `limit` to 50 items per request to keep payload sizes predictable. Queries longer
than 256 characters or empty strings are rejected with `VALIDATION_ERROR` before contacting the
upstream service.

## Request

```
GET /api/v0/search/tracks?query=<text>&limit=<n>
X-API-Key: <optional secret>
Accept: application/json
```

The adapter trims incoming queries and forwards the resolved timeout via the httpx client. A single
upstream call is executed per request.

## Normalised Track Schema

The adapter converts the raw JSON payload into `app.schemas.music.Track`. The following fields are
populated when available:

- `title` (always present)
- `artists` (list of strings)
- `album`
- `duration_s`
- `bitrate_kbps`
- `size_bytes`
- `magnet_or_path`
- `score`
- `source` (`"slskd"`)
- `external_id` (stable identifier derived from the payload)

Entries nested within `results[].files[]` are flattened in their upstream order.

## Error Mapping

| Upstream Condition | Adapter Exception | Integration Service Response |
| --- | --- | --- |
| `429 Too Many Requests` | `SlskdAdapterRateLimitedError` | `RATE_LIMITED` with `meta.retry_after_ms` and `Retry-After` header when present. |
| `5xx`, network failures, timeouts | `SlskdAdapterDependencyError` | `DEPENDENCY_ERROR` with optional `meta.provider_status`. |
| Invalid/garbled JSON | `SlskdAdapterInternalError` | `INTERNAL_ERROR`. |
| Adapter validation (empty query, limit ≤ 0) | – | `VALIDATION_ERROR`. |

A missing `Retry-After` header is replaced with the configured fallback before surfacing the rate
limit error.

## Logging

Every slskd lookup emits a structured log with `event="slskd.search"`, including status,
`duration_ms`, `limit`, `results_count` and the upstream status code. Failures log at `WARNING`
level for dependency issues and `ERROR` for malformed payloads.

## Example Response

```json
[
  {
    "title": "Smells Like Teen Spirit",
    "artists": ["Nirvana"],
    "album": "Nevermind",
    "duration_s": 301,
    "bitrate_kbps": 320,
    "size_bytes": 12345678,
    "magnet_or_path": "\\\\collector\\music\\nirvana.flac",
    "source": "slskd",
    "external_id": "abc123",
    "score": 0.92
  }
]
```

The integration service returns the above structure and raises the mapped Harmony errors for the
listed failure scenarios.
