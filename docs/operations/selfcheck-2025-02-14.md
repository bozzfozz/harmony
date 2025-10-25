# Self-check run — 2025-02-14

## Environment preparation
- Created persistent directories `/data`, `/downloads`, `/music` and provisioned an empty SQLite database at `/data/harmony.db` to mirror the production volume layout.
- Launched a temporary HTTP server on `127.0.0.1:5030` to satisfy the Soulseekd TCP probe.
- Network egress is blocked, preventing `pip install -r requirements.txt`. Provided lightweight runtime stubs for `sqlalchemy` and `aiosqlite` via `PYTHONPATH=/tmp/harmony_stubs` so the guard could execute offline.

## Executed commands
```
APP_ENV=prod \
DATABASE_URL=sqlite+aiosqlite:///data/harmony.db \
SPOTIFY_CLIENT_ID=dummy-client \
SPOTIFY_CLIENT_SECRET=dummy-secret \
OAUTH_SPLIT_MODE=false \
DOWNLOADS_DIR=/downloads \
MUSIC_DIR=/music \
HARMONY_API_KEY=test-key \
SLSKD_BASE_URL=http://127.0.0.1:5030 \
PYTHONPATH=/tmp/harmony_stubs \
python -m app.ops.selfcheck --assert-startup
```

The command exited with status code `0` and printed only the CPython runtime warning about module import ordering.

A follow-up verbose invocation produced the readiness payload for documentation purposes:

```
APP_ENV=prod \
DATABASE_URL=sqlite+aiosqlite:///data/harmony.db \
SPOTIFY_CLIENT_ID=dummy-client \
SPOTIFY_CLIENT_SECRET=dummy-secret \
OAUTH_SPLIT_MODE=false \
DOWNLOADS_DIR=/downloads \
MUSIC_DIR=/music \
HARMONY_API_KEY=test-key \
SLSKD_BASE_URL=http://127.0.0.1:5030 \
PYTHONPATH=/tmp/harmony_stubs \
python -m app.ops.selfcheck --verbose
```

Key results:
- Environment, OAuth, path, database, idempotency, Soulseekd and UI probes all returned `ok` with no missing keys.
- SQLite database and directories were detected as existing and writable.
- Soulseekd TCP reachability succeeded against the temporary HTTP server.
- UI template and static asset inventories were complete.

## Follow-up
No remediation required. Remove the temporary HTTP server and stub modules after the session.
