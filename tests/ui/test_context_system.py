from datetime import UTC, datetime

from starlette.requests import Request

from app.ui.context.base import ReadinessItem, SecretValidationResultView, ServiceHealthView
from app.ui.context.system import (
    attach_secret_result,
    build_system_integrations_context,
    build_system_liveness_context,
    build_system_page_context,
    build_system_readiness_context,
    build_system_secret_card_context,
    build_system_secret_cards,
    build_system_service_health_context,
    select_system_secret_card,
)
from app.ui.services.system import (
    IntegrationProviderStatus,
    IntegrationSummary,
    LivenessRecord,
    ReadinessDependency,
    ReadinessRecord,
    SecretValidationRecord,
    ServiceHealthBadge,
)
from app.ui.session import UiFeatures, UiSession


def _make_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/ui/system"})


def _make_session(role: str = "admin") -> UiSession:
    now = datetime.now(tz=UTC)
    return UiSession(
        identifier="session-id",
        role=role,
        features=UiFeatures(spotify=True, soulseek=True, dlq=True, imports=True),
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )


def test_build_system_page_context_registers_fragments() -> None:
    request = _make_request()
    session = _make_session()

    context = build_system_page_context(request, session=session, csrf_token="token")

    layout = context["layout"]
    assert layout.page_id == "system"
    assert any(item.href == "/ui/admin" and item.active for item in layout.navigation.primary)
    assert context["liveness_fragment"].identifier == "hx-system-liveness"
    assert context["readiness_fragment"].url.endswith("/ui/system/readiness")
    assert context["services_form"].action.endswith("/ui/system/services")
    assert len(context["secret_cards"]) == 2
    spotify_card = context["secret_cards"][0]
    assert spotify_card.slug == "spotify"
    assert spotify_card.provider == "spotify_client_secret"
    assert spotify_card.form.action.endswith("/ui/system/secrets/spotify_client_secret")


def test_build_system_page_context_uses_metrics_fallback() -> None:
    request = _make_request()
    session = _make_session()

    context = build_system_page_context(request, session=session, csrf_token="token")

    assert context["metrics_url"] == "/api/v1/metrics"


def test_build_system_liveness_context_formats_badge() -> None:
    record = LivenessRecord(status="ok", ok=True, version="1.0.0", uptime_seconds=3600.0)
    context = build_system_liveness_context(_make_request(), summary=record)

    badge = context["status_badge"]
    assert badge.variant == "success"
    assert context["status_text"] == "Ok"
    assert context["uptime_text"] == "1h"


def test_build_system_readiness_context_includes_sections() -> None:
    summary = ReadinessRecord(
        ok=False,
        database="down",
        dependencies=(ReadinessDependency(name="redis", status="down"),),
        orchestrator_components=(ReadinessDependency(name="scheduler", status="enabled"),),
        orchestrator_jobs=(ReadinessDependency(name="sync", status="disabled"),),
        enabled_jobs={"sync": False},
        error_message="maintenance",
    )
    context = build_system_readiness_context(_make_request(), summary=summary)

    database_badge = context["database_badge"]
    assert database_badge.variant == "danger"
    deps = context["dependencies"]
    assert isinstance(deps[0], ReadinessItem)
    assert context["error_message"] == "maintenance"


def test_build_system_integrations_context_renders_rows() -> None:
    summary = IntegrationSummary(
        overall="degraded",
        providers=(
            IntegrationProviderStatus(name="alpha", status="ok", details=None),
            IntegrationProviderStatus(name="beta", status="down", details={"note": "timeout"}),
        ),
    )
    context = build_system_integrations_context(_make_request(), summary=summary)

    overall = context["overall_badge"]
    assert overall.label_key == "system.status.degraded"
    assert len(context["providers"]) == 2


def test_build_system_service_health_context_formats_missing() -> None:
    badges = (
        ServiceHealthBadge(
            service="spotify",
            status="ok",
            missing=("CLIENT_ID",),
            optional_missing=(),
        ),
        ServiceHealthBadge(
            service="soulseek",
            status="fail",
            missing=(),
            optional_missing=("SLSKD_API_KEY",),
        ),
    )
    context = build_system_service_health_context(_make_request(), badges=badges)

    services = context["services"]
    assert isinstance(services[0], ServiceHealthView)
    assert services[0].badge.label_key == "system.status.fail"
    assert services[1].optional_missing == ("SLSKD_API_KEY",)


def test_secret_card_helpers_attach_results() -> None:
    cards = build_system_secret_cards()
    spotify_card = select_system_secret_card(cards, "spotify_client_secret")
    assert spotify_card is not None
    assert select_system_secret_card(cards, "spotify") is spotify_card

    record = SecretValidationRecord(
        provider="spotify_client_secret",
        mode="live",
        valid=True,
        validated_at=datetime(2024, 1, 1, tzinfo=UTC),
        reason=None,
        note="valid",
    )
    updated = attach_secret_result(spotify_card, record)

    context = build_system_secret_card_context(
        _make_request(),
        card=updated,
        csrf_token="token",
    )

    result = context["card"].result
    assert isinstance(result, SecretValidationResultView)
    assert result.badge.variant == "success"
