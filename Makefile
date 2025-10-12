SHELL := /bin/bash

.PHONY: fmt lint test dep-sync fe-build smoke doctor all fe-verify fe-install
.PHONY: supply-guard supply-guard-verbose

fmt:
	./scripts/dev/fmt.sh

lint:
	./scripts/dev/lint_py.sh

test:
	./scripts/dev/test_py.sh

dep-sync:
	./scripts/dev/dep_sync_py.sh
	./scripts/dev/dep_sync_js.sh

fe-verify:
	@bash scripts/dev/fe_install_verify.sh

fe-install:
	@SKIP_BUILD=1 SKIP_TYPECHECK=1 bash scripts/dev/fe_install_verify.sh

fe-build:
	@SKIP_INSTALL=1 SKIP_TYPECHECK=1 bash scripts/dev/fe_install_verify.sh

smoke:
	./scripts/dev/smoke_unified.sh

doctor:
	./scripts/dev/doctor.sh

all: fmt lint dep-sync test fe-build smoke

supply-guard:
	@bash scripts/dev/supply_guard.sh

supply-guard-verbose:
	@SUPPLY_GUARD_VERBOSE=1 bash scripts/dev/supply_guard.sh
