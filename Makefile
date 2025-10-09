.PHONY: help install-dev quality security analyze all db.upgrade db.revision
PY=python -m
OFF?=$(CI_OFFLINE)

help:
        @echo "make install-dev    # install dev tools"
        @echo "make quality        # isort --check-only, mypy, pytest"
        @echo "make security       # pip-audit (skips if CI_OFFLINE=true)"
        @echo "make analyze        # radon, vulture (skips if CI_OFFLINE=true)"
        @echo "make all            # run quality + security + analyze"
        @echo "make db.upgrade     # apply database migrations"
        @echo "make db.revision msg=\"...\" # autogenerate new migration"

install-dev:
	pip install -r requirements-dev.txt

quality:
        isort --check-only .
        mypy app
        pytest -q

security:
ifeq ($(OFF),true)
        @echo "⚠️ CI_OFFLINE=true → skipping security tools (pip-audit)."
else
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

db.upgrade:
        alembic downgrade base || true
        alembic upgrade head

db.revision:
ifndef msg
	$(error msg is required, usage: make db.revision msg="<description>")
endif
	alembic revision --autogenerate -m "$(msg)"
