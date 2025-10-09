# Project Completion Status

## Quality Gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Backend CI (embedded smoke harness) | ✅ | [`backend` job in `.github/workflows/ci.yml`](../../.github/workflows/ci.yml) |
| Backend CI (PostgreSQL) | ✅ | [`backend-postgres` job in `.github/workflows/ci.yml`](../../.github/workflows/ci.yml) |
| Lint & Static Analysis | ✅ | Isort, Mypy, pip-audit steps in [`backend` job](../../.github/workflows/ci.yml) |
| Coverage ≥ 85 % (changed modules) | ✅ | `pytest --cov=app/schemas/common.py --cov-report=term-missing` |
| OpenAPI drift guard | ✅ | [`openapi` job in `.github/workflows/ci.yml`](../../.github/workflows/ci.yml) |

## Evidence & Artefacts

- **CI runs:** GitHub Actions workflow [`ci.yml`](../../.github/workflows/ci.yml) provides the `backend`, `backend-postgres` and
  `openapi` jobs. Reference the corresponding job pages for individual run logs.
- **Coverage:** Execute `pytest --cov=app/schemas/common.py --cov-report=term-missing` to regenerate the coverage artefact for the
  updated schema helpers.
- **Lint/Type/Security:** Alle Gates laufen als dedizierte Schritte im `backend`-Job (`isort --check-only .`, `mypy app`,
  `pip-audit -r requirements.txt`).
- **OpenAPI drift:** The `openapi` job compares the generated schema gegen `tests/snapshots/openapi.json` and fails on drift.
