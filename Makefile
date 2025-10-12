SHELL := /bin/bash

.PHONY: fmt lint test dep-sync be-verify fe-build smoke doctor all fe-verify fe-install
.PHONY: supply-guard supply-guard-verbose supply-guard-warn

fmt:
	./scripts/dev/fmt.sh

lint:
	./scripts/dev/lint_py.sh

test:
	./scripts/dev/test_py.sh

be-verify: test

dep-sync:
	./scripts/dev/dep_sync_py.sh
	./scripts/dev/dep_sync_js.sh

fe-verify: supply-guard
        @SUPPLY_GUARD_RAN=1 bash scripts/dev/fe_install_verify.sh

fe-install: supply-guard
        @SUPPLY_GUARD_RAN=1 SKIP_BUILD=1 SKIP_TYPECHECK=1 bash scripts/dev/fe_install_verify.sh

fe-build: fe-verify
        @:

smoke:
	./scripts/dev/smoke_unified.sh

doctor:
	./scripts/dev/doctor.sh

all: fmt lint dep-sync be-verify fe-verify smoke

supply-guard:
        @bash scripts/dev/supply_guard.sh

supply-guard-verbose:
        @SUPPLY_GUARD_VERBOSE=1 bash scripts/dev/supply_guard.sh

supply-guard-warn:
        @TOOLCHAIN_STRICT=false SUPPLY_MODE=WARN bash scripts/dev/supply_guard.sh
