# Migrations Playbook

## Handling legacy `queue_jobs` payload columns

Environments created before revision `202412011200_align_postgres_types` can
have diverging schemas for the `queue_jobs` table:

- only a `payload` column (JSON/JSONB)
- only a `payload_json` column (type/nullable drift)
- both columns with partially duplicated data

Revision `202412011200_align_postgres_types` now detects these situations and
migrates them safely:

1. rename `payload` to `payload_json` when it is the sole column
2. coalesce data into `payload_json` and drop `payload` when both are present
3. normalise `payload_json` to `JSONB NOT NULL`

Operators running manual migrations no longer need to pre-clean the table—the
revision guards cover mixed states and ensure a consistent end state with a
single JSONB column.
