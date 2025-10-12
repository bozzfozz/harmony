SHELL := /bin/bash

.PHONY: fmt lint test dep-sync fe-build smoke doctor all

fmt:
	./scripts/dev/fmt.sh

lint:
	./scripts/dev/lint_py.sh

test:
	./scripts/dev/test_py.sh

dep-sync:
	./scripts/dev/dep_sync_py.sh
	./scripts/dev/dep_sync_js.sh

fe-build:
	./scripts/dev/build_fe.sh

smoke:
	./scripts/dev/smoke_unified.sh

doctor:
	./scripts/dev/doctor.sh

all: fmt lint dep-sync test fe-build smoke
