# API Documentation Route Drift

The repository scan detected discrepancies between documented system health paths and the routes that FastAPI actually exposes.

| Document | Documented Path | Actual Path | Fix |
| --- | --- | --- | --- |
| `docs/ui/fe-htmx-plan.md` (Dashboard HTMX contracts) | `GET /api/v1/system/status` | `GET /api/v1/status` | Update the dashboard polling contract to reference `/api/v1/status`.
| `docs/ui/fe-htmx-plan.md` (Dashboard HTMX contracts) | `GET /api/v1/system/health` | `GET /api/v1/health` | Replace the documented services health endpoint with `/api/v1/health`.
| `reports/ui/frontend_inventory.md` (API overview) | `/api/v1/system/status\|health\|ready\|metrics\|secrets/{provider}/validate` | `/api/v1/status`, `/api/v1/health`, `/api/v1/ready`, `/api/v1/metrics`, `/api/v1/secrets/{provider}/validate` | Expand the inventory entry so every listed action points to the concrete `/api/v1/...` routes.
| `reports/ui/frontend_inventory.md` (Dashboard wiring table) | `/api/v1/system/status`, `/api/v1/system/health` | `/api/v1/status`, `/api/v1/health` | Align the wiring table paths with the FastAPI routes.
| `reports/ui/frontend_inventory.md` (System diagnostics wiring) | `/api/v1/system/secrets/{provider}/validate` | `/api/v1/secrets/{provider}/validate` | Reference the correct secrets validation route.

