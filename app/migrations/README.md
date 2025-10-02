# Database migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) to manage schema
changes. All migration scripts live under `app/migrations` and are executed via
`alembic` commands. Migrations **must** remain additive and idempotent so that
they can run on both SQLite (the default development database) and PostgreSQL
(the production database).

## Running migrations

```bash
alembic upgrade head
alembic downgrade -1  # or "base" to reset everything
```

The Alembic configuration resolves the database URL from environment
configuration. Override the target database with the `sqlalchemy.url` value or
`DATABASE_URL` environment variable when necessary.

## Creating a new migration

1. Import all models before generating a revision so Alembic can inspect the
   declarative metadata: `from app import models  # noqa: F401`.
2. Create a revision using Alembic's CLI:

   ```bash
   alembic revision --autogenerate -m "describe change"
   ```

3. Review the generated script. Ensure every operation is **additive** and uses
   explicit guards (`has_table`, `get_columns`, `get_indexes`, …) so the script
   can run more than once without failing.
4. Provide downgrade steps. If a non-lossy downgrade is impossible, leave a
   documented `no-op` explaining why.

### Dialect compatibility

* Use SQLAlchemy types that work on both SQLite and PostgreSQL. For JSON data,
  prefer `sa.JSON().with_variant(sa.Text(), "sqlite")`.
* Avoid database-specific DDL unless wrapped in dialect checks.
* When adding NOT NULL columns to existing tables, fill historic rows and apply
  the constraint via `batch_alter_table` to keep SQLite compatible.

### Naming conventions

* Indices: `ix_<table>_<column_names>` (columns joined with underscores).
* Constraints: keep the existing `ck_`, `uq_`, `fk_` prefixes.
* Revisions: use a timestamp-like prefix and a concise slug describing the
  change, for example `202406141200_add_queue_jobs_fields_and_indexes.py`.

## Testing migrations

Run the dedicated migration smoke tests to ensure both SQLite and PostgreSQL
coverage:

```bash
pytest tests/migrations -q
```

The PostgreSQL test requires `DATABASE_URL` to point to a PostgreSQL instance.
It automatically creates and drops an isolated schema for the test run.
