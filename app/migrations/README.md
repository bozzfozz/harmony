# Database migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) to manage schema
changes for **PostgreSQL**. All migration scripts live under `app/migrations`
and assume a PostgreSQL engine configured with timezone-aware connections
(`engine_args["connect_args"]["options"]` includes `-c timezone=UTC` or an
equivalent setting).

Migrations are expected to run exactly once per environment; PostgreSQL-native
types (`JSONB`, `TIMESTAMPTZ`, partial indexes, etc.) should be used directly
without guard clauses for alternative backends.

File-based or embedded databases are intentionally unsupported. Running Alembic
against such engines can silently lose features and must be avoided in pull
requests; the legacy file-backed smoke harness exists solely for archival
regression checks.

## Running migrations

```bash
alembic upgrade head
alembic downgrade -1  # or "base" to reset everything
```

The Alembic configuration resolves the database URL from environment
configuration. Override the target database with the `sqlalchemy.url` value or
the `DATABASE_URL` environment variable when necessary. Migration tooling and
tests target PostgreSQL exclusively.

## Creating a new migration

1. Import all models before generating a revision so Alembic can inspect the
   declarative metadata: `from app import models  # noqa: F401`.
2. Create a revision using Alembic's CLI:

   ```bash
   alembic revision --autogenerate -m "describe change"
   ```

3. Review the generated script. Ensure operations are additive, rely on
   PostgreSQL primitives (e.g. `postgresql_where=` for partial indexes,
   `postgresql_using=` when altering types), and avoid conditional guards that
   skip DDL.
4. Provide downgrade steps that faithfully restore the previous schema on
   PostgreSQL. If a non-lossy downgrade is impossible, document the limitation.

### Naming conventions

* Indices: `ix_<table>_<column_names>` (columns joined with underscores).
* Constraints: keep the existing `ck_`, `uq_`, `fk_` prefixes.
* Revisions: use a timestamp-like prefix and a concise slug describing the
  change, for example `202406141200_add_queue_jobs_fields_and_indexes.py`.

## Testing migrations

Run the dedicated migration smoke tests to ensure PostgreSQL coverage:

```bash
pytest tests/migrations -q
```

`DATABASE_URL` must point to a PostgreSQL instance. The test suite creates and
drops an isolated schema for each run.
