# UI Smoke Checks (Local)

The `scripts/dev/ui_smoke_local.sh` helper boots the Harmony API with an
in-memory configuration and runs a set of HTTP checks against the UI
routes. The script is intended for quick, deterministic health checks
that mirror the CI smoke automation.

## Runtime Dependencies

The smoke checks require the production runtime packages `uvicorn` and
`httpx` (plus their transitive dependencies). Materialise them with
`uv sync`; offline environments can rely on the cached wheel workflow
described below.

### Online Workflow

1. From the repository root, install the backend requirements with uv:
   ```bash
   uv sync
   ```
2. Run the smoke script via uv:
   ```bash
   uv run make ui-smoke
   ```

### Offline / Air-Gapped Workflow

Prepare the wheel cache on a machine that **does** have internet access:

1. Run the caching helper and point it at a directory that can be
   transferred to the target environment (defaults to
   `.cache/ui-smoke-wheels`):
   ```bash
   bash scripts/dev/cache_ui_smoke_wheels.sh /path/to/export/ui-smoke-wheels
   ```
2. Copy the populated directory to the target environment.
3. On the target machine, set `UI_SMOKE_WHEEL_DIR` to the directory that
   contains the cached wheels (skip this step if you placed the cache at
   `<repo>/.cache/ui-smoke-wheels`):
   ```bash
   export UI_SMOKE_WHEEL_DIR=/path/to/export/ui-smoke-wheels
   ```
4. Execute the smoke script. It will attempt to satisfy missing
   dependencies from the cache before falling back to PyPI:
   ```bash
   uv run make ui-smoke
   ```

If both the cache lookup and the network install fail, the script aborts
with guidance to re-run the caching helper.

## Logs and Temporary Artifacts

The script writes logs and scratch data under `.tmp/`:

- `.tmp/ui-smoke.log` – captured uvicorn output.
- `.tmp/ui-smoke.db` – temporary SQLite database used for the run.

Artifacts are deleted automatically when the process exits, except for
log files which are preserved for post-mortem inspection.
