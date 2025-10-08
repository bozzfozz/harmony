# Database migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) to manage schema
changes. All migration scripts live under `app/migrations` and are executed via
`alembic` commands. Migrations **must** remain additive and idempotent so that
they can run repeatedly against PostgreSQL without manual clean-up.

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

### Dialekt-Hinweise

* Verwende native PostgreSQL-Typen (`sa.JSON`, `sa.JSONB`, `sa.UUID`, …) und
  nutze `postgresql_using=`/`postgresql_where=` für partielle Indizes statt
  SQLite-Fallbacks.
* Vermeide datenbank-spezifische DDL ohne Guards; prüfe z. B. mit
  `if connection.dialect.name == "postgresql"` bevor du Postgres-spezifische
  Funktionen aufrufst.
* Beim Hinzufügen von NOT NULL-Spalten zu bestehenden Tabellen: Fülle Alt-Daten
  in denselben Migrationen und setze die Constraint anschließend via
  `batch_alter_table`.

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

The PostgreSQL test requires `DATABASE_URL` to point to a PostgreSQL instance.
It automatically creates and drops an isolated schema for the test run.
