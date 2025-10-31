# Quality Gates Overview

Harmony no longer ships an automated test suite. Operational safety now depends on
runtime smoke checks, type validation and dependency audits:

- `uv run make all` runs formatting, linting, dependency synchronisation, supply-guard
  and the backend smoke harness.
- `uv run make docs-verify` confirms documentation references stay in sync with the
  repository layout.
- `uv run make pip-audit` scans the locked dependency set for known vulnerabilities.
- `uv run make ui-smoke` signs into the UI, exercises the main dashboards and validates
  rendered fragments.

For a fully aggregated gate, execute `uv run make release-check`. The script orchestrates
all required checks sequentially and fails fast on the first error.

Manual verification remains encouraged for critical flows (HDM imports, OAuth setups,
Soulseek connectivity). Capture findings in runbooks under `docs/operations/` to keep the
knowledge base current.
