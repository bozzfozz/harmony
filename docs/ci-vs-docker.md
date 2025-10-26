# Backend CI vs. Docker Build Checks

The repository defines two primary GitHub Actions workflows for backend quality gates and Docker image publication. They share some steps but are not identical in scope.

## `backend-ci` workflow

The `backend-ci` workflow runs on every push and pull request. Its single job, `Backend quality gates`, installs both runtime and dev/test dependencies and then executes a focused set of make targets:

- `make docs-verify`
- `make fmt`
- `make lint`
- `make test`
- `make smoke`

These commands are invoked directly in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) and correspond to the default quality checks (formatting, linting, tests, and basic smoke validation). The workflow does **not** call `make release-check` and therefore does not run security scanning via `pip-audit`.

## `docker-image` workflow

The `docker-image` workflow is used when building and optionally publishing container images. After dependency installation, it runs `make release-check` before producing any Docker artifacts. `make release-check` expands to `make all`, `make docs-verify`, `make pip-audit`, and `make ui-smoke` as defined in the [`Makefile`](../Makefile). The `make all` target already covers `fmt`, `lint`, `dep-sync`, `test`, `supply-guard`, and `smoke`, so `release-check` is a superset of the backend CI checks with additional gates.

Because `release-check` includes `make pip-audit`, the Docker workflow fails whenever `pip-audit` reports a vulnerability in `requirements.txt`, `requirements-dev.txt`, or `requirements-test.txt`. In the Starlette advisory case (`GHSA-2c2j-9gv5-cj73`), backend CI still passes because it never invokes `pip-audit`, while the Docker workflow aborts due to the failing security gate. Updating the pinned Starlette version in `requirements.txt` resolves the discrepancy.

For LinuxServer.io publication runs, append `make image-lsio` followed by `make smoke-lsio`. The smoke harness starts the LSIO
container, waits up to 60 seconds for `/api/health/ready`, and asserts that `/config/harmony.db` exists to catch bootstrap
regressions before pushing to `ghcr.io`.
