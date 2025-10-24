# SQLite Migration Smoke Test

## Setup

```
rm -f tmp.db && touch tmp.db
```

## Execution

```
python - <<'PY'
from sqlalchemy import create_engine
from app.db_migrations import apply_schema_migrations

engine = create_engine("sqlite:///tmp.db")
apply_schema_migrations(engine)
apply_schema_migrations(engine)
PY
```

## Observations

- Running the migration helper twice on a fresh database completed without raising errors, confirming the helper is idempotent for missing tables.
- No tables were created because the helper only adds optional columns to existing tables; inspecting the database yields empty schemas:

```
sqlite3 tmp.db '.tables'
# (no tables)

sqlite3 tmp.db '.schema playlists'
# (no output — table absent)

sqlite3 tmp.db '.schema backfill_jobs'
# (no output — table absent)
```

## Notes

- The base schema must be created via `Base.metadata.create_all(...)` before the migration helper can add columns to `playlists` or `backfill_jobs`.
- Double application remains safe because each guard checks for column existence prior to issuing `ALTER TABLE` statements.
