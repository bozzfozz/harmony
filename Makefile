SHELL := /bin/bash

.PHONY: fmt lint test dep-sync be-verify smoke doctor all lint-fix precommit ui-guard ui-smoke docs-verify release-check pip-audit package-verify image-lsio smoke-lsio
.PHONY: supply-guard supply-guard-verbose supply-guard-warn
.PHONY: foss-scan foss-enforce

fmt:
	./scripts/dev/fmt.sh

lint:
	./scripts/dev/lint_py.sh

test:
	./scripts/dev/test_py.sh

be-verify: test

dep-sync:
	./scripts/dev/dep_sync_py.sh

smoke:
	./scripts/dev/smoke_unified.sh

image-lsio:
	docker build -f docker/Dockerfile.lsio -t ghcr.io/bozzfozz/harmony:lsio .

smoke-lsio:
	./scripts/dev/smoke_lsio.sh

doctor:
	./scripts/dev/doctor.sh
docs-verify:
	@python scripts/docs_reference_guard.py

pip-audit:
	./scripts/dev/pip_audit.sh


ui-guard:
	./scripts/dev/ui_guard.sh

ui-smoke:
	./scripts/dev/ui_smoke_local.sh

all:
	@set -euo pipefail; \
		$(MAKE) fmt; \
		$(MAKE) lint; \
		$(MAKE) dep-sync; \
		$(MAKE) be-verify; \
		$(MAKE) supply-guard; \
		$(MAKE) smoke

release-check:
	@set -euo pipefail; \
		$(MAKE) all; \
		$(MAKE) docs-verify; \
		$(MAKE) pip-audit; \
		$(MAKE) ui-smoke

package-verify:
	@python scripts/dev/package_verify.py

lint-fix:
	@set -euo pipefail; \
		while true; do \
			before="$$(git diff --binary | sha256sum | awk '{print $$1}')"; \
			ruff format .; \
			ruff check --select I --fix .; \
			ruff check --fix .; \
			after="$$(git diff --binary | sha256sum | awk '{print $$1}')"; \
			if [ "$$before" = "$$after" ]; then \
				break; \
			fi; \
			done

precommit:
	@if command -v pre-commit >/dev/null 2>&1; then \
		pre-commit run -a; \
	else \
		echo "[warn] pre-commit nicht installiert, Target \u00fcbersprungen"; \
	fi

supply-guard:
	@bash scripts/dev/supply_guard.sh

supply-guard-verbose:
	@SUPPLY_GUARD_VERBOSE=1 bash scripts/dev/supply_guard.sh

supply-guard-warn:
	@TOOLCHAIN_STRICT=false SUPPLY_MODE=WARN bash scripts/dev/supply_guard.sh

foss-scan:
	@bash scripts/dev/foss_guard.sh

foss-enforce:
	@FOSS_STRICT=true bash scripts/dev/foss_guard.sh

