from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.system import router as system_router
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
        dependencies={"spotify": "up", "orchestrator:job:sync": "idle"},
    )
    service = StubHealthService(result)
    app = _create_app(service, orchestrator_status={"enabled_jobs": {"sync": True}})
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
                "jobs": {"sync": "idle"},
                "enabled_jobs": {"sync": True},
            },
        },
        "error": None,
    }
    assert "migrations" not in response.text


def test_ready_endpoint_failure_returns_503_without_migrations() -> None:
    result = ReadinessResult(
        ok=False,
        database="down",
        dependencies={"spotify": "down", "orchestrator:worker": "down"},
    )
    service = StubHealthService(result)
    app = _create_app(service, orchestrator_status={"enabled_jobs": {}})
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["ok"] is False
    error = payload["error"]
    assert error["code"] == "DEPENDENCY_ERROR"
    meta = error.get("meta", {})
    assert meta["db"] == "down"
    assert meta["deps"] == {"spotify": "down", "orchestrator:worker": "down"}
    assert meta["orchestrator"] == {
        "components": {"worker": "down"},
        "jobs": {},
        "enabled_jobs": {},
    }
    assert "migrations" not in response.text
    assert "migrations" not in meta


def test_ready_handler_has_no_migrations_reference() -> None:
    contents = Path("app/api/system.py").read_text(encoding="utf-8")
    attribute = "." + "migrations"
    key = '"' + "migrations" + '"'
    assert attribute not in contents
    assert key not in contents
