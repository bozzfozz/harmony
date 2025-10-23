from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.system import router as system_router
from app.ops.selfcheck import ReadyIssue, ReadyReport
from app.services.health import ReadinessResult


class StubHealthService:
    def __init__(self, result: ReadinessResult) -> None:
        self._result = result

    async def readiness(self) -> ReadinessResult:
        return self._result


def _create_app(service: StubHealthService, orchestrator_status: dict | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(system_router)
    app.state.health_service = service
    if orchestrator_status is not None:
        app.state.orchestrator_status = orchestrator_status
    return app


def test_ready_endpoint_success_has_no_migrations_key() -> None:
    result = ReadinessResult(
        ok=True,
        database="up",
        dependencies={
            "spotify": "up",
            "orchestrator:job:sync": "idle",
            "orchestrator:job:artist_sync": "idle",
        },
    )
    service = StubHealthService(result)
    app = _create_app(
        service,
        orchestrator_status={"enabled_jobs": {"artist_sync": True, "sync": True}},
    )
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "ok": True,
        "data": {
            "db": "up",
            "deps": {"spotify": "up"},
            "orchestrator": {
                "components": {},
                "jobs": {"artist_sync": "idle", "sync": "idle"},
                "enabled_jobs": {"artist_sync": True, "sync": True},
            },
        },
        "error": None,
    }
    assert "migrations" not in response.text
    jobs = payload["data"]["orchestrator"]["jobs"]
    assert "artist_sync" in jobs and jobs["artist_sync"] == "idle"
    enabled_jobs = payload["data"]["orchestrator"]["enabled_jobs"]
    assert "artist_sync" in enabled_jobs and enabled_jobs["artist_sync"] is True


def test_ready_endpoint_failure_returns_503_without_migrations() -> None:
    result = ReadinessResult(
        ok=False,
        database="down",
        dependencies={
            "spotify": "down",
            "orchestrator:worker": "down",
            "orchestrator:job:artist_sync": "down",
        },
    )
    service = StubHealthService(result)
    app = _create_app(service, orchestrator_status={"enabled_jobs": {"artist_sync": False}})
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["ok"] is False
    error = payload["error"]
    assert error["code"] == "DEPENDENCY_ERROR"
    meta = error.get("meta", {})
    assert meta["db"] == "down"
    assert meta["deps"] == {
        "spotify": "down",
        "orchestrator:worker": "down",
        "orchestrator:job:artist_sync": "down",
    }
    assert meta["orchestrator"] == {
        "components": {"worker": "down"},
        "jobs": {"artist_sync": "down"},
        "enabled_jobs": {"artist_sync": False},
    }
    assert "migrations" not in response.text
    assert "migrations" not in meta


def test_ready_handler_has_no_migrations_reference() -> None:
    contents = Path("app/api/system.py").read_text(encoding="utf-8")
    attribute = "." + "migrations"
    key = '"' + "migrations" + '"'
    assert attribute not in contents
    assert key not in contents


def test_system_status_reports_readiness_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    result = ReadinessResult(
        ok=True,
        database="up",
        dependencies={"ui:assets": "down"},
    )
    service = StubHealthService(result)

    failure_report = ReadyReport(
        status="fail",
        checks={"ui": {"status": "fail"}},
        issues=[
            ReadyIssue(
                component="ui",
                message="templates missing",
                exit_code=70,
                details={
                    "templates": {"missing": ["pages/dashboard.j2"], "unreadable": [], "empty": []},
                    "static": {"missing": [], "unreadable": [], "empty": []},
                },
            )
        ],
    )

    monkeypatch.setattr("app.api.system.aggregate_ready", lambda: failure_report)
    monkeypatch.setattr("app.api.system._WORKERS", {})

    @contextmanager
    def _session_scope_stub():
        yield object()

    monkeypatch.setattr("app.api.system.session_scope", _session_scope_stub)
    monkeypatch.setattr("app.api.system.evaluate_all_service_health", lambda session: {})

    app = _create_app(service)
    client = TestClient(app)

    response = client.get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    readiness = payload["readiness"]
    assert readiness["status"] == "fail"
    issues = readiness["issues"]
    assert any(issue["component"] == "ui" for issue in issues)
