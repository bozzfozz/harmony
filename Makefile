SHELL := /bin/bash

.PHONY: fmt lint test dep-sync be-verify smoke doctor all
.PHONY: supply-guard supply-guard-verbose supply-guard-warn vendor-frontend vendor-frontend-reset

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

doctor:
	./scripts/dev/doctor.sh

all: fmt lint dep-sync be-verify supply-guard smoke

supply-guard:
	@bash scripts/dev/supply_guard.sh

supply-guard-verbose:
	@SUPPLY_GUARD_VERBOSE=1 bash scripts/dev/supply_guard.sh

supply-guard-warn:
        @TOOLCHAIN_STRICT=false SUPPLY_MODE=WARN bash scripts/dev/supply_guard.sh

vendor-frontend:
	./scripts/dev/vendor_frontend.sh

vendor-frontend-reset:
	./scripts/dev/vendor_frontend.sh --reset

