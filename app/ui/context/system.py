from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from fastapi import Request

from app.api.router_registry import compose_prefix
from app.dependencies import get_app_config
from app.ui.formatters import format_datetime_display
from app.ui.services.system import (
    IntegrationSummary,
    LivenessRecord,
    ReadinessDependency,
    ReadinessRecord,
    SecretValidationRecord,
    ServiceHealthBadge,
)
from app.ui.session import UiSession

from .base import (
    AsyncFragment,
    FormDefinition,
    FormField,
    IntegrationRow,
    LayoutContext,
    MetaTag,
    ReadinessItem,
    SecretValidationCard,
    SecretValidationResultView,
    ServiceHealthView,
    StatusBadge,
    StatusVariant,
    _build_primary_navigation,
    _format_duration_seconds,
    _format_status_text,
    _normalize_status,
    _safe_url_for,
    _system_status_badge,
)


def _resolve_api_base_path(request: Request) -> str:
    scope_app = request.scope.get("app")
    if scope_app is not None:
        state = getattr(scope_app, "state", None)
        if state is not None:
            base_path = getattr(state, "api_base_path", None)
            if isinstance(base_path, str):
                return base_path
    return get_app_config().api_base_path


def _build_secret_cards() -> tuple[SecretValidationCard, ...]:
    providers = (
        (
            "spotify",
            "spotify_client_secret",
            "system.secrets.spotify.title",
            "system.secrets.spotify.description",
        ),
        (
            "soulseek",
            "slskd_api_key",
            "system.secrets.soulseek.title",
            "system.secrets.soulseek.description",
        ),
    )
    cards: list[SecretValidationCard] = []
    for slug, provider, title_key, description_key in providers:
        identifier = f"system-secret-{slug}"
        form = FormDefinition(
            identifier=f"{identifier}-form",
            method="post",
            action=f"/ui/system/secrets/{provider}",
            submit_label_key="system.secrets.validate",
            fields=(
                FormField(
                    name="value",
                    input_type="password",
                    label_key="system.secrets.override",
                    autocomplete="off",
                ),
            ),
        )
        cards.append(
            SecretValidationCard(
                identifier=identifier,
                slug=slug,
                provider=provider,
                title_key=title_key,
                description_key=description_key,
                form=form,
                target_id=f"hx-{identifier}",
            )
        )
    return tuple(cards)


def _build_secret_result(
    card: SecretValidationCard, record: SecretValidationRecord
) -> SecretValidationResultView:
    badge_label = "system.status.valid" if record.valid else "system.status.invalid"
    badge_variant: StatusVariant = "success" if record.valid else "danger"
    badge = StatusBadge(
        label_key=badge_label,
        variant=badge_variant,
        test_id=f"{card.identifier}-status",
    )
    mode_key = f"system.secrets.mode.{_normalize_status(record.mode)}"
    validated_at = format_datetime_display(record.validated_at)
    return SecretValidationResultView(
        provider=record.provider,
        badge=badge,
        mode_key=mode_key,
        validated_at=validated_at,
        note=record.note,
        reason=record.reason,
    )


def _build_readiness_items(
    items: Sequence[ReadinessDependency],
    *,
    prefix: str,
) -> tuple[ReadinessItem, ...]:
    rows: list[ReadinessItem] = []
    for item in items:
        safe_name = item.name.replace(" ", "-").lower()
        badge = _system_status_badge(item.status, test_id=f"{prefix}-{safe_name}")
        rows.append(ReadinessItem(name=item.name, badge=badge))
    return tuple(rows)


def build_system_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="system",
        role=session.role,
        navigation=_build_primary_navigation(session, active="admin"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    liveness_url = _safe_url_for(request, "system_liveness_fragment", "/ui/system/liveness")
    readiness_url = _safe_url_for(request, "system_readiness_fragment", "/ui/system/readiness")
    integrations_url = _safe_url_for(
        request,
        "system_integrations_fragment",
        "/ui/system/integrations",
    )
    services_url = _safe_url_for(request, "system_services_fragment", "/ui/system/services")

    liveness_fragment = AsyncFragment(
        identifier="hx-system-liveness",
        url=liveness_url,
        target="#hx-system-liveness",
        loading_key="system-liveness",
    )
    readiness_fragment = AsyncFragment(
        identifier="hx-system-readiness",
        url=readiness_url,
        target="#hx-system-readiness",
        loading_key="system-readiness",
    )
    integrations_fragment = AsyncFragment(
        identifier="hx-system-integrations",
        url=integrations_url,
        target="#hx-system-integrations",
        loading_key="system-integrations",
    )
    services_fragment = AsyncFragment(
        identifier="hx-system-services",
        url=services_url,
        target="#hx-system-services",
        loading_key="system-services",
    )

    liveness_form = FormDefinition(
        identifier="system-liveness-refresh",
        method="get",
        action=liveness_url,
        submit_label_key="system.health.refresh",
    )
    readiness_form = FormDefinition(
        identifier="system-readiness-refresh",
        method="get",
        action=readiness_url,
        submit_label_key="system.health.refresh",
    )
    integrations_form = FormDefinition(
        identifier="system-integrations-refresh",
        method="get",
        action=integrations_url,
        submit_label_key="system.integrations.refresh",
    )
    services_form = FormDefinition(
        identifier="system-services-refresh",
        method="get",
        action=services_url,
        submit_label_key="system.services.refresh",
    )

    secret_cards = build_system_secret_cards()
    metrics_fallback = compose_prefix(_resolve_api_base_path(request), "/metrics")
    metrics_url = _safe_url_for(request, "get_metrics", metrics_fallback)

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "liveness_fragment": liveness_fragment,
        "readiness_fragment": readiness_fragment,
        "integrations_fragment": integrations_fragment,
        "services_fragment": services_fragment,
        "liveness_form": liveness_form,
        "readiness_form": readiness_form,
        "integrations_form": integrations_form,
        "services_form": services_form,
        "secret_cards": secret_cards,
        "metrics_url": metrics_url,
    }


def build_system_liveness_context(
    request: Request,
    *,
    summary: LivenessRecord,
) -> Mapping[str, Any]:
    status_badge = _system_status_badge(summary.status, test_id="system-liveness-status")
    return {
        "request": request,
        "status_badge": status_badge,
        "status_text": _format_status_text(summary.status),
        "version": summary.version,
        "uptime_text": _format_duration_seconds(summary.uptime_seconds),
    }


def build_system_readiness_context(
    request: Request,
    *,
    summary: ReadinessRecord,
) -> Mapping[str, Any]:
    database_status = summary.database or "unknown"
    database_badge = _system_status_badge(database_status, test_id="system-readiness-database")
    dependencies = _build_readiness_items(summary.dependencies, prefix="system-readiness-dep")
    components = _build_readiness_items(
        summary.orchestrator_components,
        prefix="system-readiness-component",
    )
    jobs = _build_readiness_items(summary.orchestrator_jobs, prefix="system-readiness-job")
    enabled_jobs = tuple(sorted(name for name, enabled in summary.enabled_jobs.items() if enabled))
    disabled_jobs = tuple(
        sorted(name for name, enabled in summary.enabled_jobs.items() if not enabled)
    )
    return {
        "request": request,
        "database_badge": database_badge,
        "database_status_text": _format_status_text(database_status),
        "dependencies": dependencies,
        "components": components,
        "jobs": jobs,
        "enabled_jobs": enabled_jobs,
        "disabled_jobs": disabled_jobs,
        "error_message": summary.error_message,
    }


def build_system_integrations_context(
    request: Request,
    *,
    summary: IntegrationSummary,
) -> Mapping[str, Any]:
    overall_badge = _system_status_badge(summary.overall, test_id="system-integrations-status")
    rows: list[IntegrationRow] = []
    for provider in summary.providers:
        safe_name = provider.name.replace(" ", "-").lower()
        rows.append(
            IntegrationRow(
                name=provider.name,
                badge=_system_status_badge(
                    provider.status,
                    test_id=f"system-integrations-{safe_name}-status",
                ),
                details=provider.details,
            )
        )
    return {
        "request": request,
        "overall_badge": overall_badge,
        "overall_status_text": _format_status_text(summary.overall),
        "providers": tuple(rows),
    }


def build_system_service_health_context(
    request: Request,
    *,
    badges: Sequence[ServiceHealthBadge],
) -> Mapping[str, Any]:
    services: list[ServiceHealthView] = []
    for badge in badges:
        status_value = badge.status
        if badge.missing:
            status_value = "fail"
        safe_name = badge.service.replace(" ", "-").lower()
        services.append(
            ServiceHealthView(
                service=badge.service,
                badge=_system_status_badge(
                    status_value,
                    test_id=f"system-service-{safe_name}-status",
                ),
                missing=tuple(badge.missing),
                optional_missing=tuple(badge.optional_missing),
            )
        )
    return {
        "request": request,
        "services": tuple(services),
    }


def build_system_secret_cards() -> tuple[SecretValidationCard, ...]:
    return _build_secret_cards()


def select_system_secret_card(
    cards: Sequence[SecretValidationCard],
    provider: str,
) -> SecretValidationCard | None:
    normalized = provider.strip().lower()
    for card in cards:
        if card.provider == normalized or card.slug == normalized:
            return card
    return None


def attach_secret_result(
    card: SecretValidationCard,
    record: SecretValidationRecord,
) -> SecretValidationCard:
    result_view = _build_secret_result(card, record)
    return replace(card, result=result_view)


def build_system_secret_card_context(
    request: Request,
    *,
    card: SecretValidationCard,
    csrf_token: str,
) -> Mapping[str, Any]:
    return {
        "request": request,
        "card": card,
        "csrf_token": csrf_token,
    }


__all__ = [
    "build_system_page_context",
    "build_system_liveness_context",
    "build_system_readiness_context",
    "build_system_integrations_context",
    "build_system_service_health_context",
    "build_system_secret_cards",
    "select_system_secret_card",
    "attach_secret_result",
    "build_system_secret_card_context",
]
