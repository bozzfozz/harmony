from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.ui.services.system import (
    IntegrationSummary,
    LivenessRecord,
    ReadinessRecord,
    SecretValidationRecord,
    SystemUiService,
)


def _make_request() -> Request:
    scope = {"type": "http", "method": "GET", "path": "/ui/system"}
    return Request(scope)


class _StubContext:
    def __enter__(self) -> SimpleNamespace:
        return SimpleNamespace()

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - context protocol
        return None


@pytest.mark.asyncio
async def test_fetch_liveness_combines_sources(monkeypatch) -> None:
    async def fake_live() -> dict[str, str]:
        return {"status": "ok"}

    async def fake_health(_: Request) -> dict[str, object]:
        return {"data": {"status": "ok", "version": "1.2.3", "uptime_s": 42.0}}

    monkeypatch.setattr("app.ui.services.system.health_api.live", fake_live)
    monkeypatch.setattr("app.ui.services.system.system_api.get_health", fake_health)

    service = SystemUiService(integration_service=SimpleNamespace())
    record = await service.fetch_liveness(_make_request())

    assert isinstance(record, LivenessRecord)
    assert record.status == "ok"
    assert record.version == "1.2.3"
    assert record.uptime_seconds == 42.0


@pytest.mark.asyncio
async def test_fetch_readiness_normalises_dependencies(monkeypatch) -> None:
    async def fake_readiness(_: Request) -> dict[str, object]:
        return {
            "ok": False,
            "error": {"message": "dependency failure"},
            "data": {
                "db": "up",
                "deps": {"redis": "down", "api": "up"},
                "orchestrator": {
                    "components": {"scheduler": "enabled"},
                    "jobs": {"artist_sync": "enabled", "sync": "disabled"},
                    "enabled_jobs": {
                        "artist_sync": True,
                        "sync": False,
                        "match": True,
                    },
                },
            },
        }

    monkeypatch.setattr("app.ui.services.system.system_api.get_readiness", fake_readiness)
    service = SystemUiService(integration_service=SimpleNamespace())
    record = await service.fetch_readiness(_make_request())

    assert isinstance(record, ReadinessRecord)
    assert record.ok is False
    assert record.database == "up"
    assert record.error_message == "dependency failure"
    assert [item.name for item in record.dependencies] == ["api", "redis"]
    assert [item.status for item in record.dependencies] == ["up", "down"]
    assert list(record.enabled_jobs.keys()) == ["artist_sync", "match", "sync"]


@pytest.mark.asyncio
async def test_fetch_readiness_handles_response_envelope(monkeypatch) -> None:
    async def fake_readiness(_: Request) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": {"message": "dependency failure"},
                "data": {"deps": {"redis": "down"}},
            },
        )

    monkeypatch.setattr("app.ui.services.system.system_api.get_readiness", fake_readiness)
    service = SystemUiService(integration_service=SimpleNamespace())
    record = await service.fetch_readiness(_make_request())

    assert isinstance(record, ReadinessRecord)
    assert record.ok is False
    assert record.error_message == "dependency failure"
    assert [item.name for item in record.dependencies] == ["redis"]
    assert [item.status for item in record.dependencies] == ["down"]


@pytest.mark.asyncio
async def test_fetch_integrations_sorts_providers(monkeypatch) -> None:
    async def fake_integrations(service) -> SimpleNamespace:  # noqa: ARG001 - signature match
        providers = [
            SimpleNamespace(name="beta", status="down", details={"region": "us"}),
            SimpleNamespace(name="alpha", status="up", details=None),
        ]
        data = SimpleNamespace(overall="degraded", providers=providers)
        return SimpleNamespace(ok=True, data=data)

    monkeypatch.setattr(
        "app.ui.services.system.integrations_router.get_integrations",
        fake_integrations,
    )

    service = SystemUiService(integration_service=SimpleNamespace())
    summary = await service.fetch_integrations()

    assert isinstance(summary, IntegrationSummary)
    assert summary.overall == "degraded"
    assert [provider.name for provider in summary.providers] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_validate_secret_translates_envelope(monkeypatch) -> None:
    async def fake_validate(provider, request, payload, session):  # noqa: ARG001
        validated = SimpleNamespace(
            mode="live", valid=True, at=payload.value or object(), reason=None, note="OK"
        )
        data = SimpleNamespace(provider=provider.lower(), validated=validated)
        return SimpleNamespace(ok=True, data=data, error=None)

    monkeypatch.setattr("app.ui.services.system.system_api.validate_secret", fake_validate)

    service = SystemUiService(integration_service=SimpleNamespace())
    record = await service.validate_secret(
        _make_request(),
        provider="Spotify",
        override="token",
        session=SimpleNamespace(),
    )

    assert isinstance(record, SecretValidationRecord)
    assert record.provider == "spotify"
    assert record.valid is True
    assert record.note == "OK"


@pytest.mark.asyncio
async def test_fetch_service_badges_returns_sorted(monkeypatch) -> None:
    def fake_evaluate(session) -> dict[str, SimpleNamespace]:  # noqa: ARG001
        return {
            "spotify": SimpleNamespace(status="ok", missing=("CLIENT_ID",), optional_missing=()),
            "soulseek": SimpleNamespace(
                status="fail", missing=(), optional_missing=("SLSKD_API_KEY",)
            ),
        }

    monkeypatch.setattr("app.ui.services.system.session_scope", lambda: _StubContext())
    monkeypatch.setattr(
        "app.ui.services.system.evaluate_all_service_health",
        fake_evaluate,
    )

    service = SystemUiService(integration_service=SimpleNamespace())
    badges = await service.fetch_service_badges()

    assert isinstance(badges, tuple)
    assert [badge.service for badge in badges] == ["soulseek", "spotify"]
    assert badges[0].status == "fail"
