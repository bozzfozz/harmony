# Dead-Letter Queue Management API

The DLQ management API exposes read and maintenance operations for downloads that
exhausted all retry attempts and entered the `dead_letter` state. All endpoints
are served under the authenticated prefix `/api/v1/dlq` and require a valid
API key.

## Endpoints

### `GET /api/v1/dlq`

Returns a paginated list of DLQ entries ordered by `created_at` (default) or
`updated_at` timestamps. Query parameters:

| Parameter   | Type      | Default | Description |
|-------------|-----------|---------|-------------|
| `page`      | integer   | `1`     | 1-indexed page number. |
| `page_size` | integer   | `25`    | Page size (1-100, configurable via `DLQ_PAGE_SIZE_*`). |
| `reason`    | string    | —       | Optional substring filter applied to the stored error message. |
| `from`      | ISO date  | —       | Lower bound (inclusive) on `created_at`. |
| `to`        | ISO date  | —       | Upper bound (inclusive) on `created_at`. |
| `order_by`  | enum      | `created_at` | Sort column (`created_at` or `updated_at`). |
| `order_dir` | enum      | `desc`  | Sort direction (`asc` or `desc`). |

Response shape:

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "id": "42",
        "entity": "download",
        "reason": "network",
        "message": "network timeout",
        "created_at": "2025-03-01T08:00:00Z",
        "updated_at": "2025-03-01T08:05:00Z",
        "retry_count": 5
      }
    ],
    "page": 1,
    "page_size": 25,
    "total": 128
  },
  "error": null
}
```

The `reason` field is derived from the leading token of the persisted error
message (e.g. `"network timeout" → "network"`).

### `POST /api/v1/dlq/requeue`

Bulk re-enqueues DLQ entries. The payload must contain 1..500 identifiers
(configurable via `DLQ_REQUEUE_LIMIT`):

```json
{ "ids": ["41", "42"] }
```

Successful responses list requeued IDs and skipped entries with reasons:

```json
{
  "ok": true,
  "data": {
    "requeued": ["41"],
    "skipped": [
      { "id": "42", "reason": "already_queued" }
    ]
  },
  "error": null
}
```

An error envelope is returned if any identifier does not exist (`NOT_FOUND`) or
if validation fails (`VALIDATION_ERROR`). Requeue requests are idempotent –
already queued downloads are reported under `skipped` without modifying state.

### `POST /api/v1/dlq/purge`

Deletes DLQ entries by explicit identifier list or by retention filters.
Exactly one strategy must be provided:

```json
{ "ids": ["41", "42"] }
```

or

```json
{ "older_than": "2025-02-01T00:00:00Z", "reason": "network" }
```

The optional `reason` filter applies to the stored error message. The response
contains the number of deleted rows:

```json
{ "ok": true, "data": { "purged": 37 }, "error": null }
```

Requests that omit both `ids` and `older_than` (or supply both) are rejected
with `VALIDATION_ERROR`. The bulk purge limit defaults to 1 000 entries and can
be tuned via `DLQ_PURGE_LIMIT`.

### `GET /api/v1/dlq/stats`

Returns aggregate DLQ statistics:

```json
{
  "ok": true,
  "data": {
    "total": 123,
    "by_reason": {
      "network": 50,
      "auth": 10,
      "unknown": 63
    },
    "last_24h": 17
  },
  "error": null
}
```

## Logging Signals

DLQ operations emit structured logs that replace the former Prometheus gauges:

- `event=dlq.requeue` with `requeued`, `skipped`, `actor`, `duration_ms`.
- `event=dlq.purge` with `purged`, `reason`, `actor`, `duration_ms`.
- `event=dlq.stats` with `total`, `last_24h`, `distinct_reasons`, `duration_ms`.

Forward these logs to your log aggregation stack (Loki, ELK, etc.) and build
alerts/dashboards to track requeue/purge activity over time.

## Limits & Configuration

Environment variables control runtime limits:

| Variable | Default | Description |
|----------|---------|-------------|
| `DLQ_PAGE_SIZE_DEFAULT` | `25` | Default `page_size` for listings. |
| `DLQ_PAGE_SIZE_MAX` | `100` | Maximum allowed `page_size`. |
| `DLQ_REQUEUE_LIMIT` | `500` | Maximum IDs per requeue call. |
| `DLQ_PURGE_LIMIT` | `1000` | Maximum IDs or matched rows per purge call. |

## Open Questions

The downloads table does not persist a dedicated “reason” column; therefore the
API derives a reason slug from the leading token of the stored error message.
If the schema gains an explicit reason field in the future the service can use
it directly for filtering and reporting without altering the public API.

