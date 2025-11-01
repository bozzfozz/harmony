# Backend CI vs. Docker Build Checks

The repository defines two primary GitHub Actions workflows for backend quality gates and Docker image publication. They share core steps but target different release moments.

## `release-check` workflow

The [`release-check`](../.github/workflows/release-check.yml) workflow runs on release branches, release tags, and manual dispatches. After installing runtime and dev dependencies via `uv sync --frozen --project . --extra dev --extra test` it executes:

- `uv run --no-sync --extra dev --extra test make release-check`, which expands to:
  - `make all` (Formatierung, Linting, Dependency-Sync, Supply-Guard, Smoke)
  - `make docs-verify`
  - `make pip-audit` (läuft intern mit `--strict`)
  - `make ui-smoke`
- `uv run --no-sync --extra dev --extra test make package-verify`, sodass Installation, Wheel-Build und `python -m build` nach jedem Gate reproduzierbar bleiben.

Während des Laufs erzwingt der Workflow einen sauberen `git diff --exit-code`, schreibt strukturierte Logs nach `reports/release-check/release-check.log` und lädt die Artefakte `release-check-logs` sowie `release-packaging-artifacts` hoch.

## `docker-image` workflow

Das manuell auslösbare [`docker-image`](../.github/workflows/docker-image.yml) wiederholt denselben `make release-check`-Gate-Lauf (inklusive `git diff --exit-code`) bevor Docker-Artefakte gebaut werden. Anschließend erstellt der Workflow Multi-Arch-Images über `docker/build-push-action`, versieht sie mit Metadaten und pusht sie zu `ghcr.io`. Ist der Eingabeparameter `smoke_enabled=true`, startet der Lauf optional einen Container-Smoketest, der `/api/health/ready` bis zu 60 Sekunden pollt.

Für LinuxServer.io-Publikationen können `make image-lsio` und `make smoke-lsio` nachgeschaltet werden. Das Smoke-Harness startet den LSIO-Container, wartet bis zu 60 Sekunden auf `/api/health/ready` und stellt sicher, dass `/config/harmony.db` im Container sowie auf dem Host vorhanden ist, bevor Images veröffentlicht werden.
