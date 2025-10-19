from __future__ import annotations

from types import SimpleNamespace

from app.integrations.health import IntegrationHealth, ProviderHealth
from app.schemas import StatusResponse
from app.ui.services.soulseek import SoulseekUiService


class _StubRegistry:
    def __init__(self) -> None:
        self.initialised = False

    def initialise(self) -> None:
        self.initialised = True

    def track_providers(self) -> dict[str, object]:
        return {}


def _make_service(
    *,
    soulseek_overrides: dict[str, object] | None = None,
    security_overrides: dict[str, object] | None = None,
) -> SoulseekUiService:
    base_soulseek = {
        "base_url": "https://slskd.example",
        "api_key": "token",
        "timeout_ms": 8_000,
        "retry_max": 3,
        "retry_backoff_base_ms": 250,
        "retry_jitter_pct": 20.0,
        "preferred_formats": ("flac", "mp3"),
        "max_results": 50,
    }
    base_security = {
        "profile": "default",
        "require_auth": True,
        "rate_limiting_enabled": True,
    }
    if soulseek_overrides:
        base_soulseek.update(soulseek_overrides)
    if security_overrides:
        base_security.update(security_overrides)

    config = SimpleNamespace(
        soulseek=SimpleNamespace(**base_soulseek),
        security=SimpleNamespace(**base_security),
    )
    registry = _StubRegistry()
    return SoulseekUiService(
        request=SimpleNamespace(),
        config=config,
        soulseek_client=SimpleNamespace(),
        registry=registry,
    )


def test_suggested_tasks_reflects_healthy_configuration() -> None:
    service = _make_service()
    status = StatusResponse(status="ok")
    health = IntegrationHealth(
        overall="ok",
        providers=(ProviderHealth(provider="soulseek", status="ok", details={}),),
    )

    tasks = service.suggested_tasks(status=status, health=health)

    assert len(tasks) == 10
    assert all(task.completed for task in tasks)


def test_suggested_tasks_flags_gaps_and_limits_count() -> None:
    service = _make_service(
        soulseek_overrides={
            "api_key": "",
            "preferred_formats": (),
            "retry_max": 1,
            "retry_jitter_pct": 0.0,
            "timeout_ms": 12_000,
            "max_results": 200,
        },
        security_overrides={
            "require_auth": False,
            "rate_limiting_enabled": False,
        },
    )
    status = StatusResponse(status="down")
    health = IntegrationHealth(
        overall="down",
        providers=(ProviderHealth(provider="soulseek", status="down", details={}),),
    )

    tasks = service.suggested_tasks(status=status, health=health, limit=5)

    assert len(tasks) == 5
    flags = {
        task.identifier: task.completed
        for task in service.suggested_tasks(status=status, health=health)
    }
    assert flags["daemon"] is False
    assert flags["providers"] is False
    assert flags["api-key"] is False
    assert flags["preferred-formats"] is False
    assert flags["retry-policy"] is False
    assert flags["retry-jitter"] is False
    assert flags["timeout"] is False
    assert flags["max-results"] is False
    assert flags["require-auth"] is False
    assert flags["rate-limiting"] is False
