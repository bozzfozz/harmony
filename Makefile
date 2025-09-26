.PHONY: help install-dev quality security analyze all
PY=python -m
OFF?=$(CI_OFFLINE)

help:
	@echo "make install-dev    # install dev tools"
	@echo "make quality        # ruff, black --check, mypy, pytest"
	@echo "make security       # bandit, pip-audit (skips if CI_OFFLINE=true)"
	@echo "make analyze        # radon, vulture (skips if CI_OFFLINE=true)"
	@echo "make all            # run quality + security + analyze"

install-dev:
	pip install -r requirements-dev.txt

quality:
	ruff check .
	black --check .
	mypy app
	pytest -q

security:
ifeq ($(OFF),true)
	@echo "⚠️ CI_OFFLINE=true → skipping security tools (bandit, pip-audit)."
else
	bandit -q -r app
	pip-audit -r requirements.txt || true
endif

analyze:
ifeq ($(OFF),true)
	@echo "⚠️ CI_OFFLINE=true → skipping analyze tools (radon, vulture)."
else
	radon cc -s -a app
	vulture app tests --exclude .venv
endif

all: quality security analyze
