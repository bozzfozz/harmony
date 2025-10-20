from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from html import escape
import json
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

from fastapi import Request
from starlette.datastructures import URL

from app.api.search import DEFAULT_SOURCES
from app.config import SecurityConfig, SoulseekConfig, get_env
from app.integrations.health import IntegrationHealth
from app.schemas import SOULSEEK_RETRYABLE_STATES, StatusResponse
from app.ui.formatters import format_datetime_display
from app.ui.session import UiFeatures, UiSession

if TYPE_CHECKING:
    from app.ui.services import (
        DownloadPage,
        DownloadRow,
        OrchestratorJob,
        ArtistPreferenceRow,
        SettingRow,
        SearchResultsPage,
        SoulseekUploadRow,
        SpotifyAccountSummary,
        SpotifyArtistRow,
        SpotifyBackfillSnapshot,
        SpotifyBackfillTimelineEntry,
        SpotifyFreeIngestJobSnapshot,
        SpotifyFreeIngestResult,
        SpotifyManualResult,
        SpotifyOAuthHealth,
        SpotifyPlaylistFilterOption,
        SpotifyPlaylistItemRow,
        SpotifyPlaylistRow,
        SpotifyRecommendationRow,
        SpotifyRecommendationSeed,
        SpotifySavedTrackRow,
        SpotifyStatus,
        SpotifyTopArtistRow,
        SpotifyTopTrackRow,
        SpotifyTrackDetail,
        WatchlistRow,
        SettingsHistoryRow,
        SettingsOverview,
        IntegrationProviderStatus,
        IntegrationSummary,
        LivenessRecord,
        ReadinessDependency,
        ReadinessRecord,
        SecretValidationRecord,
        ServiceHealthBadge,
    )

AlertLevel = Literal["info", "success", "warning", "error"]
ButtonMethod = Literal["get", "post"]
HxMethod = Literal["get", "post", "put", "patch", "delete"]
StatusVariant = Literal["success", "danger", "muted"]


@dataclass(slots=True)
class NavItem:
    label_key: str
    href: str
    active: bool = False
    test_id: str | None = None
    badge: StatusBadge | None = None


@dataclass(slots=True)
class NavigationContext:
    primary: Sequence[NavItem] = field(default_factory=tuple)


@dataclass(slots=True)
class AlertMessage:
    level: AlertLevel
    text: str


@dataclass(slots=True)
class MetaTag:
    name: str
    content: str


@dataclass(slots=True)
class ModalDefinition:
    identifier: str
    title_key: str
    body: str


@dataclass(slots=True)
class DefinitionItem:
    label_key: str
    value: str
    test_id: str | None = None
    is_missing: bool = False


@dataclass(slots=True)
class LayoutContext:
    page_id: str
    role: str | None
    navigation: NavigationContext = field(default_factory=NavigationContext)
    alerts: Sequence[AlertMessage] = field(default_factory=tuple)
    head_meta: Sequence[MetaTag] = field(default_factory=tuple)
    modals: Sequence[ModalDefinition] = field(default_factory=tuple)


@dataclass(slots=True)
class ScriptResource:
    uses_cdn: bool
    cdn_url: str | None
    integrity: str | None
    crossorigin: str | None
    local_asset_path: str


@dataclass(slots=True)
class UiAssetConfig:
    htmx: ScriptResource


# CDN metadata aligns with HTMX v1.9.10 from the official distribution.
_HTMX_CDN_URL = "https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js"
_HTMX_CDN_INTEGRITY = "sha384-ylwRez2oJ6TP2RFxYDs2fzGEylh4G6dkprdFM5lTyBC0bY4Z1cdqUPVHtVHCnRvW"
_CDN_CROSSORIGIN = "anonymous"
_HTMX_LOCAL_PATH = "js/htmx.min.js"


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_ui_assets() -> UiAssetConfig:
    allow_cdn = _parse_bool(get_env("UI_ALLOW_CDN"))
    cdn_url = get_env("UI_HTMX_CDN_URL") or _HTMX_CDN_URL
    cdn_integrity = get_env("UI_HTMX_CDN_SRI") or _HTMX_CDN_INTEGRITY

    uses_cdn = allow_cdn and bool(cdn_url) and bool(cdn_integrity)

    resource = ScriptResource(
        uses_cdn=uses_cdn,
        cdn_url=cdn_url if uses_cdn else None,
        integrity=cdn_integrity if uses_cdn else None,
        crossorigin=_CDN_CROSSORIGIN if uses_cdn else None,
        local_asset_path=_HTMX_LOCAL_PATH,
    )
    return UiAssetConfig(htmx=resource)


@dataclass(slots=True)
class FormField:
    name: str
    input_type: str
    label_key: str
    autocomplete: str | None = None
    required: bool = False


@dataclass(slots=True)
class CheckboxOption:
    value: str
    label_key: str
    checked: bool = False
    test_id: str | None = None


@dataclass(slots=True)
class CheckboxGroup:
    name: str
    legend_key: str
    description_key: str | None = None
    options: Sequence[CheckboxOption] = field(default_factory=tuple)


@dataclass(slots=True)
class FormDefinition:
    identifier: str
    method: ButtonMethod
    action: str
    submit_label_key: str
    fields: Sequence[FormField] = field(default_factory=tuple)
    checkbox_groups: Sequence[CheckboxGroup] = field(default_factory=tuple)


@dataclass(slots=True)
class ActionButton:
    identifier: str
    label_key: str


@dataclass(slots=True)
class SuggestedTask:
    identifier: str
    title_key: str
    description_key: str | None = None
    completed: bool = False


@dataclass(slots=True)
class CallToActionCard:
    identifier: str
    title_key: str
    description_key: str
    href: str
    link_label_key: str
    link_test_id: str | None = None


@dataclass(slots=True)
class StatusBadge:
    label_key: str
    variant: StatusVariant
    test_id: str | None = None


@dataclass(slots=True)
class TableCell:
    text_key: str | None = None
    text: str | None = None
    html: str | None = None
    badge: StatusBadge | None = None
    test_id: str | None = None
    form: "TableCellForm" | None = None
    forms: Sequence["TableCellForm"] = field(default_factory=tuple)


@dataclass(slots=True)
class ReadinessItem:
    name: str
    badge: StatusBadge


@dataclass(slots=True)
class IntegrationRow:
    name: str
    badge: StatusBadge
    details: Mapping[str, object] | None = None


@dataclass(slots=True)
class SecretValidationResultView:
    provider: str
    badge: StatusBadge
    mode_key: str
    validated_at: str | None
    note: str | None
    reason: str | None


@dataclass(slots=True)
class SecretValidationCard:
    identifier: str
    provider: str
    title_key: str
    description_key: str
    form: FormDefinition
    target_id: str
    result: SecretValidationResultView | None = None


@dataclass(slots=True)
class ServiceHealthView:
    service: str
    badge: StatusBadge
    missing: Sequence[str] = field(default_factory=tuple)
    optional_missing: Sequence[str] = field(default_factory=tuple)


def _build_external_link_cell(
    url: str | None,
    *,
    cell_test_id: str,
    anchor_test_id: str,
    label: str,
    aria_label: str,
) -> TableCell:
    if not url:
        return TableCell(text="—", test_id=cell_test_id)

    anchor_html = (
        f'<a class="table-external-link" '
        f'href="{escape(url, quote=True)}" '
        'target="_blank" '
        'rel="noopener" '
        f'data-test="{escape(anchor_test_id, quote=True)}" '
        f'aria-label="{escape(aria_label, quote=True)}">'
        f"{escape(label)} "
        '<span class="table-external-link__icon" aria-hidden="true">↗</span>'
        "</a>"
    )
    return TableCell(html=anchor_html, test_id=cell_test_id)


def _normalize_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    if not normalized:
        return "unknown"
    return normalized


def _status_variant(status: str) -> StatusVariant:
    normalized = _normalize_status(status)
    if normalized in {"ok", "up", "ready", "enabled", "connected", "valid", "passing"}:
        return "success"
    if normalized in {"disabled", "not_required", "pending", "unknown", "n/a"}:
        return "muted"
    return "danger"


def _system_status_badge(status: str, *, test_id: str | None = None) -> StatusBadge:
    normalized = _normalize_status(status)
    safe_key = normalized.replace(" ", "-").replace(":", "-").replace("/", "-")
    label_key = f"system.status.{safe_key}"
    variant = _status_variant(normalized)
    return StatusBadge(label_key=label_key, variant=variant, test_id=test_id)


def _format_status_text(status: str) -> str:
    normalized = _normalize_status(status)
    return normalized.replace("_", " ").title()


def _format_duration_seconds(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total_seconds = int(max(seconds, 0))
    if total_seconds <= 0:
        return "<1s"
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts or secs:
        parts.append(f"{secs}s")
    return " ".join(parts)


@dataclass(slots=True)
class TableRow:
    cells: Sequence[TableCell]
    test_id: str | None = None


@dataclass(slots=True)
class TableDefinition:
    identifier: str
    column_keys: Sequence[str]
    rows: Sequence[TableRow]
    caption_key: str | None = None


@dataclass(slots=True)
class PaginationContext:
    label_key: str
    target: str
    swap: str = "outerHTML"
    previous_url: str | None = None
    next_url: str | None = None


@dataclass(slots=True)
class TableFragment:
    identifier: str
    table: TableDefinition
    empty_state_key: str
    data_attributes: Mapping[str, str] = field(default_factory=dict)
    pagination: PaginationContext | None = None


@dataclass(slots=True)
class TableCellForm:
    action: str
    method: ButtonMethod
    submit_label_key: str
    hidden_fields: Mapping[str, str] = field(default_factory=dict)
    hx_target: str | None = None
    hx_swap: str = "innerHTML"
    disabled: bool = False
    hx_method: HxMethod = "post"
    test_id: str | None = None


@dataclass(slots=True)
class AsyncFragment:
    identifier: str
    url: str
    target: str
    load_event: str = "load"
    poll_interval_seconds: int | None = None
    swap: str = "outerHTML"
    loading_key: str = "loading"

    @property
    def trigger(self) -> str:
        parts = [self.load_event]
        if self.poll_interval_seconds is not None:
            parts.append(f"every {self.poll_interval_seconds}s")
        return ", ".join(parts)


@dataclass(slots=True)
class SpotifyTimeRangeOption:
    value: str
    label: str
    url: str
    active: bool
    test_id: str


_SPOTIFY_TIME_RANGE_LABELS: Mapping[str, str] = {
    "short_term": "Last 4 weeks",
    "medium_term": "Last 6 months",
    "long_term": "All time",
}


def _build_time_range_options(
    request: Request,
    *,
    endpoint_name: str,
    fragment_id: str,
    selected: str,
    fallback_path: str,
) -> tuple[SpotifyTimeRangeOption, ...]:
    try:
        base_raw = request.url_for(endpoint_name)
    except Exception:
        base_raw = fallback_path
    base_url = URL(str(base_raw))
    options: list[SpotifyTimeRangeOption] = []
    for value, label in _SPOTIFY_TIME_RANGE_LABELS.items():
        option_url = base_url.include_query_params(time_range=value)
        options.append(
            SpotifyTimeRangeOption(
                value=value,
                label=label,
                url=str(option_url),
                active=value == selected,
                test_id=f"{fragment_id}-range-{value}",
            )
        )
    return tuple(options)


@dataclass(slots=True)
class SpotifyFreeIngestFormContext:
    csrf_token: str
    playlist_value: str
    tracks_value: str
    accepted_items: Sequence[DefinitionItem] = field(default_factory=tuple)
    skipped_items: Sequence[DefinitionItem] = field(default_factory=tuple)
    result: SpotifyFreeIngestResult | None = None
    form_errors: Mapping[str, str] = field(default_factory=dict)
    upload_error: str | None = None


@dataclass(slots=True)
class SpotifyFreeIngestJobContext:
    job_id: str
    state: str
    counts: Sequence[DefinitionItem]
    accepted_items: Sequence[DefinitionItem]
    skipped_items: Sequence[DefinitionItem]
    queued_tracks: int
    failed_tracks: int
    skipped_tracks: int
    error: str | None = None
    skip_reason: str | None = None


_SEARCH_SOURCE_LABELS: dict[str, str] = {
    "spotify": "search.sources.spotify",
    "soulseek": "search.sources.soulseek",
}


def _normalise_status(value: str) -> str:
    return value.strip().lower() if value else ""


def _status_badge(
    *,
    status: str,
    test_id: str,
    success_label: str,
    degraded_label: str,
    down_label: str,
    unknown_label: str,
    degrade_is_warning: bool = True,
) -> StatusBadge:
    normalised = _normalise_status(status)
    if normalised in {"connected", "ok", "online"}:
        return StatusBadge(label_key=success_label, variant="success", test_id=test_id)
    if normalised in {"disconnected", "down", "failed", "error"}:
        return StatusBadge(label_key=down_label, variant="danger", test_id=test_id)
    if normalised == "degraded":
        variant: StatusVariant = "danger" if degrade_is_warning else "muted"
        return StatusBadge(label_key=degraded_label, variant=variant, test_id=test_id)
    return StatusBadge(label_key=unknown_label, variant="muted", test_id=test_id)


def build_soulseek_navigation_badge(
    *,
    connection: StatusResponse | None,
    integration: IntegrationHealth | None,
    test_id: str = "nav-soulseek-status",
) -> StatusBadge:
    connection_status = _normalise_status(connection.status if connection else "")
    integration_status = _normalise_status(integration.overall if integration else "")

    if (
        connection_status in {"disconnected", "down", "failed", "error"}
        or integration_status == "down"
    ):
        return StatusBadge(
            label_key="soulseek.integration.down",
            variant="danger",
            test_id=test_id,
        )

    if connection_status == "degraded" or integration_status == "degraded":
        return StatusBadge(
            label_key="soulseek.integration.degraded",
            variant="danger",
            test_id=test_id,
        )

    if connection_status in {"connected", "ok", "online"} and integration_status in {"", "ok"}:
        label_key = (
            "soulseek.integration.ok" if integration_status == "ok" else "soulseek.status.connected"
        )
        return StatusBadge(label_key=label_key, variant="success", test_id=test_id)

    if integration_status == "ok":
        return StatusBadge(
            label_key="soulseek.integration.ok",
            variant="success",
            test_id=test_id,
        )

    return StatusBadge(
        label_key="soulseek.integration.unknown",
        variant="muted",
        test_id=test_id,
    )


def _format_health_details(details: Mapping[str, Any]) -> str:
    if not details:
        return ""
    rendered: list[str] = []
    for key, value in details.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            rendered.append(f"{key}: {value}")
            continue
        try:
            rendered.append(f"{key}: {json.dumps(value, sort_keys=True)}")
        except TypeError:
            rendered.append(f"{key}: {value}")
    return ", ".join(rendered)


def _safe_url_for(request: Request, name: str, fallback: str) -> str:
    try:
        resolved = URL(str(request.url_for(name)))
        if resolved.query:
            return f"{resolved.path}?{resolved.query}"
        return resolved.path
    except Exception:  # pragma: no cover - fallback for tests
        return fallback


def _download_action_base_url(
    request: Request, name: str, fallback_template: str
) -> str:
    try:
        resolved = URL(str(request.url_for(name, download_id="0")))
    except Exception:  # pragma: no cover - fallback for tests
        return fallback_template

    segments = [segment for segment in resolved.path.split("/") if segment]
    for index, segment in enumerate(segments):
        if segment == "0":
            segments[index] = "{download_id}"
            break
    else:
        return fallback_template

    path = "/" + "/".join(segments)
    if resolved.query:
        return f"{path}?{resolved.query}"
    return path


def _build_search_form(default_sources: Sequence[str]) -> FormDefinition:
    default_source_set = {source for source in default_sources}
    ordered_sources = list(_SEARCH_SOURCE_LABELS.keys())
    for source in DEFAULT_SOURCES:
        if source not in ordered_sources:
            ordered_sources.append(source)

    checkbox_options: list[CheckboxOption] = []
    for source in ordered_sources:
        label_key = _SEARCH_SOURCE_LABELS.get(source, f"search.sources.{source}")
        checkbox_options.append(
            CheckboxOption(
                value=source,
                label_key=label_key,
                checked=source in default_source_set,
                test_id=f"search-source-{source}",
            )
        )

    sources_group = CheckboxGroup(
        name="sources",
        legend_key="search.sources.legend",
        description_key="search.sources.description",
        options=tuple(checkbox_options),
    )

    return FormDefinition(
        identifier="search-form",
        method="post",
        action="/ui/search/results",
        submit_label_key="search.submit",
        fields=(
            FormField(
                name="query",
                input_type="search",
                label_key="search.query",
                autocomplete="off",
                required=True,
            ),
            FormField(
                name="limit",
                input_type="number",
                label_key="search.limit",
            ),
        ),
        checkbox_groups=(sources_group,),
    )


def build_login_page_context(request: Request, *, error: str | None = None) -> Mapping[str, Any]:
    alerts: list[AlertMessage] = []
    if error:
        alerts.append(AlertMessage(level="error", text=error))

    layout = LayoutContext(
        page_id="login",
        role="anonymous",
        alerts=tuple(alerts),
    )

    login_form = FormDefinition(
        identifier="login-form",
        method="post",
        action="/ui/login",
        submit_label_key="login.submit",
        fields=(
            FormField(
                name="api_key",
                input_type="password",
                label_key="login.api_key",
                autocomplete="off",
                required=True,
            ),
        ),
    )

    return {
        "request": request,
        "layout": layout,
        "form": login_form,
    }


def _build_primary_navigation(
    session: UiSession,
    *,
    active: str,
    soulseek_badge: StatusBadge | None = None,
) -> NavigationContext:
    items: list[NavItem] = [
        NavItem(
            label_key="nav.home",
            href="/ui",
            active=active == "home",
            test_id="nav-home",
        )
    ]

    if session.features.spotify and session.allows("operator"):
        items.append(
            NavItem(
                label_key="nav.spotify",
                href="/ui/spotify",
                active=active == "spotify",
                test_id="nav-spotify",
            )
        )

    if session.features.soulseek and session.allows("operator"):
        items.append(
            NavItem(
                label_key="nav.soulseek",
                href="/ui/soulseek",
                active=active in {"soulseek", "search"},
                test_id="nav-soulseek",
                badge=soulseek_badge,
            )
        )

    if session.allows("operator"):
        items.append(
            NavItem(
                label_key="nav.operations",
                href="/ui/operations",
                active=active == "operations",
                test_id="nav-operator",
            )
        )

    if session.allows("admin"):
        items.append(
            NavItem(
                label_key="nav.admin",
                href="/ui/admin",
                active=active == "admin",
                test_id="nav-admin",
            )
        )

    return NavigationContext(primary=tuple(items))


def build_primary_navigation(
    session: UiSession,
    *,
    active: str,
    soulseek_badge: StatusBadge | None = None,
) -> NavigationContext:
    """Public wrapper to build the primary navigation context."""

    return _build_primary_navigation(
        session,
        active=active,
        soulseek_badge=soulseek_badge,
    )


def build_dashboard_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    actions: list[ActionButton] = []

    if session.allows("operator"):
        actions.append(
            ActionButton(
                identifier="operator-action",
                label_key="dashboard.action.operator",
            )
        )

    if session.allows("admin"):
        actions.append(
            ActionButton(
                identifier="admin-action",
                label_key="dashboard.action.admin",
            )
        )

    layout = LayoutContext(
        page_id="dashboard",
        role=session.role,
        navigation=_build_primary_navigation(session, active="home"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    features_table = _build_features_table(session.features)

    try:
        activity_url = request.url_for("activity_table")
    except Exception:
        activity_url = "/ui/activity/table"

    activity_fragment = AsyncFragment(
        identifier="hx-activity-table",
        url=activity_url,
        target="#hx-activity-table",
        poll_interval_seconds=60,
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "features_table": features_table,
        "actions": tuple(actions),
        "csrf_token": csrf_token,
        "activity_fragment": activity_fragment,
    }


def _build_secret_cards() -> tuple[SecretValidationCard, ...]:
    providers = (
        ("spotify", "system.secrets.spotify.title", "system.secrets.spotify.description"),
        ("soulseek", "system.secrets.soulseek.title", "system.secrets.soulseek.description"),
    )
    cards: list[SecretValidationCard] = []
    for provider, title_key, description_key in providers:
        identifier = f"system-secret-{provider}"
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
    metrics_url = _safe_url_for(request, "get_metrics", "/api/system/metrics")

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


def build_admin_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="admin",
        role=session.role,
        navigation=_build_primary_navigation(session, active="admin"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    call_to_actions = (
        CallToActionCard(
            identifier="admin-system-card",
            title_key="admin.system.title",
            description_key="admin.system.description",
            href="/ui/system",
            link_label_key="admin.system.link",
            link_test_id="admin-system-link",
        ),
        CallToActionCard(
            identifier="admin-settings-card",
            title_key="admin.settings.title",
            description_key="admin.settings.description",
            href="/ui/settings",
            link_label_key="admin.settings.link",
            link_test_id="admin-settings-link",
        ),
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "call_to_actions": call_to_actions,
    }


def _build_settings_form_definition() -> FormDefinition:
    return FormDefinition(
        identifier="settings-update-form",
        method="post",
        action="/ui/settings",
        submit_label_key="settings.save",
        fields=(
            FormField(
                name="key",
                input_type="text",
                label_key="settings.key",
                required=True,
            ),
            FormField(
                name="value",
                input_type="text",
                label_key="settings.value",
            ),
        ),
    )


def _build_settings_table(rows: Sequence[SettingRow]) -> TableDefinition:
    table_rows: list[TableRow] = []
    for row in rows:
        value_cell = (
            TableCell(text=row.value)
            if row.value not in (None, "")
            else TableCell(text_key="settings.value.unset")
        )
        status_key = (
            "settings.override.present" if row.has_override else "settings.override.missing"
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.key),
                    value_cell,
                    TableCell(text_key=status_key),
                ),
                test_id=f"setting-row-{row.key}",
            )
        )
    return TableDefinition(
        identifier="settings-table",
        column_keys=("settings.key", "settings.value", "settings.override"),
        rows=tuple(table_rows),
        caption_key="settings.table.caption",
    )


def _build_settings_form_components(
    overview: SettingsOverview,
) -> tuple[FormDefinition, TableDefinition, str]:
    form = _build_settings_form_definition()
    table = _build_settings_table(overview.rows)
    updated_display = format_datetime_display(overview.updated_at)
    return form, table, updated_display


def build_settings_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    overview: SettingsOverview,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="settings",
        role=session.role,
        navigation=_build_primary_navigation(session, active="admin"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    settings_form, settings_table, updated_display = _build_settings_form_components(overview)

    history_url = _safe_url_for(request, "settings_history_fragment", "/ui/settings/history")
    preferences_url = _safe_url_for(
        request, "settings_artist_preferences_fragment", "/ui/settings/artist-preferences"
    )

    history_fragment = AsyncFragment(
        identifier="hx-settings-history",
        url=history_url,
        target="#hx-settings-history",
        loading_key="settings-history",
    )
    history_form = FormDefinition(
        identifier="settings-history-refresh",
        method="get",
        action=history_url,
        submit_label_key="settings.history.refresh",
    )

    artist_fragment = AsyncFragment(
        identifier="hx-settings-artist-preferences",
        url=preferences_url,
        target="#hx-settings-artist-preferences",
        loading_key="settings-artist-preferences",
    )
    artist_form = FormDefinition(
        identifier="settings-artist-preferences-refresh",
        method="get",
        action=preferences_url,
        submit_label_key="settings.artist_preferences.refresh",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "settings_form": settings_form,
        "settings_table": settings_table,
        "settings_updated_at_display": updated_display,
        "history_fragment": history_fragment,
        "history_refresh_form": history_form,
        "artist_preferences_fragment": artist_fragment,
        "artist_preferences_refresh_form": artist_form,
    }


def build_settings_form_fragment_context(
    request: Request,
    *,
    overview: SettingsOverview,
) -> Mapping[str, Any]:
    settings_form, settings_table, updated_display = _build_settings_form_components(overview)
    return {
        "request": request,
        "settings_form": settings_form,
        "settings_table": settings_table,
        "settings_updated_at_display": updated_display,
    }


def build_settings_history_fragment_context(
    request: Request,
    *,
    rows: Sequence[SettingsHistoryRow],
) -> Mapping[str, Any]:
    table_rows: list[TableRow] = []
    for entry in rows:
        old_cell = (
            TableCell(text=entry.old_value)
            if entry.old_value not in (None, "")
            else TableCell(text_key="settings.value.unset")
        )
        new_cell = (
            TableCell(text=entry.new_value)
            if entry.new_value not in (None, "")
            else TableCell(text_key="settings.value.unset")
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=entry.key),
                    old_cell,
                    new_cell,
                    TableCell(text=format_datetime_display(entry.changed_at)),
                ),
            )
        )

    table = TableDefinition(
        identifier="settings-history-table",
        column_keys=(
            "settings.history.key",
            "settings.history.old",
            "settings.history.new",
            "settings.history.changed",
        ),
        rows=tuple(table_rows),
        caption_key="settings.history.caption",
    )

    fragment = TableFragment(
        identifier="hx-settings-history",
        table=table,
        empty_state_key="settings-history",
        data_attributes={"count": str(len(table_rows))},
    )

    return {"request": request, "fragment": fragment}


def build_settings_artist_preferences_fragment_context(
    request: Request,
    *,
    rows: Sequence[ArtistPreferenceRow],
    csrf_token: str,
) -> Mapping[str, Any]:
    table_rows: list[TableRow] = []
    for row in rows:
        state_key = (
            "settings.artist_preferences.state.enabled"
            if row.selected
            else "settings.artist_preferences.state.disabled"
        )
        target_state = "false" if row.selected else "true"
        toggle_label = (
            "settings.artist_preferences.disable"
            if row.selected
            else "settings.artist_preferences.enable"
        )
        toggle_form = TableCellForm(
            action="/ui/settings/artist-preferences",
            method="post",
            submit_label_key=toggle_label,
            hidden_fields={
                "csrftoken": csrf_token,
                "action": "toggle",
                "artist_id": row.artist_id,
                "release_id": row.release_id,
                "selected": target_state,
            },
            hx_target="#hx-settings-artist-preferences",
            hx_swap="outerHTML",
            test_id=f"artist-preference-toggle-{row.artist_id}-{row.release_id}",
        )
        remove_form = TableCellForm(
            action="/ui/settings/artist-preferences",
            method="post",
            submit_label_key="settings.artist_preferences.remove",
            hidden_fields={
                "csrftoken": csrf_token,
                "action": "remove",
                "artist_id": row.artist_id,
                "release_id": row.release_id,
            },
            hx_target="#hx-settings-artist-preferences",
            hx_swap="outerHTML",
            test_id=f"artist-preference-remove-{row.artist_id}-{row.release_id}",
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.artist_id),
                    TableCell(text=row.release_id),
                    TableCell(text_key=state_key),
                    TableCell(forms=(toggle_form, remove_form)),
                ),
            )
        )

    table = TableDefinition(
        identifier="settings-artist-preferences-table",
        column_keys=(
            "settings.artist_preferences.artist",
            "settings.artist_preferences.release",
            "settings.artist_preferences.selected",
            "settings.artist_preferences.actions",
        ),
        rows=tuple(table_rows),
        caption_key="settings.artist_preferences.caption",
    )

    fragment = TableFragment(
        identifier="hx-settings-artist-preferences",
        table=table,
        empty_state_key="settings-artist-preferences",
        data_attributes={"count": str(len(table_rows))},
    )

    add_form = FormDefinition(
        identifier="settings-artist-preferences-add",
        method="post",
        action="/ui/settings/artist-preferences",
        submit_label_key="settings.artist_preferences.add",
        fields=(
            FormField(
                name="artist_id",
                input_type="text",
                label_key="settings.artist_preferences.artist",
                required=True,
            ),
            FormField(
                name="release_id",
                input_type="text",
                label_key="settings.artist_preferences.release",
                required=True,
            ),
            FormField(
                name="selected",
                input_type="checkbox",
                label_key="settings.artist_preferences.selected",
            ),
        ),
    )

    return {
        "request": request,
        "fragment": fragment,
        "add_form": add_form,
        "csrf_token": csrf_token,
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
        if card.provider == normalized:
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


def build_operations_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="operations",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    downloads_fragment: AsyncFragment | None = None
    jobs_fragment: AsyncFragment | None = None
    if session.features.dlq:
        # Operations overview tables are non-critical; defer loading until the
        # user scrolls them into view to reduce the initial render cost.
        downloads_fragment = AsyncFragment(
            identifier="hx-downloads-table",
            url=_safe_url_for(request, "downloads_table", "/ui/downloads/table"),
            target="#hx-downloads-table",
            poll_interval_seconds=15,
            loading_key="downloads",
            load_event="revealed",
        )
        jobs_fragment = AsyncFragment(
            identifier="hx-jobs-table",
            url=_safe_url_for(request, "jobs_table", "/ui/jobs/table"),
            target="#hx-jobs-table",
            poll_interval_seconds=15,
            loading_key="jobs",
            load_event="revealed",
        )

    watchlist_fragment = AsyncFragment(
        identifier="hx-watchlist-table",
        url=_safe_url_for(request, "watchlist_table", "/ui/watchlist/table"),
        target="#hx-watchlist-table",
        poll_interval_seconds=30,
        loading_key="watchlist",
        load_event="revealed",
    )

    activity_fragment = AsyncFragment(
        identifier="hx-activity-table",
        url=_safe_url_for(request, "activity_table", "/ui/activity/table"),
        target="#hx-activity-table",
        poll_interval_seconds=60,
        loading_key="activity",
        load_event="revealed",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "downloads_fragment": downloads_fragment,
        "jobs_fragment": jobs_fragment,
        "watchlist_fragment": watchlist_fragment,
        "activity_fragment": activity_fragment,
        "dashboard_url": "/ui",
        "downloads_page_url": "/ui/downloads",
        "jobs_page_url": "/ui/jobs",
        "watchlist_page_url": "/ui/watchlist",
        "activity_page_url": "/ui/activity",
    }


def build_downloads_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="downloads",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    downloads_fragment = AsyncFragment(
        identifier="hx-downloads-table",
        url=_safe_url_for(request, "downloads_table", "/ui/downloads/table"),
        target="#hx-downloads-table",
        poll_interval_seconds=15,
        loading_key="downloads",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "downloads_fragment": downloads_fragment,
        "operations_url": "/ui/operations",
    }


def build_jobs_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="jobs",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    jobs_fragment = AsyncFragment(
        identifier="hx-jobs-table",
        url=_safe_url_for(request, "jobs_table", "/ui/jobs/table"),
        target="#hx-jobs-table",
        poll_interval_seconds=15,
        loading_key="jobs",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "jobs_fragment": jobs_fragment,
        "operations_url": "/ui/operations",
    }


def build_watchlist_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="watchlist",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    watchlist_fragment = AsyncFragment(
        identifier="hx-watchlist-table",
        url=_safe_url_for(request, "watchlist_table", "/ui/watchlist/table"),
        target="#hx-watchlist-table",
        poll_interval_seconds=30,
        loading_key="watchlist",
    )

    watchlist_form = FormDefinition(
        identifier="watchlist-create-form",
        method="post",
        action="/ui/watchlist",
        submit_label_key="watchlist.create",
        fields=(
            FormField(
                name="artist_key",
                input_type="text",
                label_key="watchlist.artist",
                required=True,
            ),
            FormField(
                name="priority",
                input_type="number",
                label_key="watchlist.priority",
            ),
        ),
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "watchlist_fragment": watchlist_fragment,
        "watchlist_form": watchlist_form,
        "operations_url": "/ui/operations",
    }


def build_activity_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="activity",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    activity_fragment = AsyncFragment(
        identifier="hx-activity-table",
        url=_safe_url_for(request, "activity_table", "/ui/activity/table"),
        target="#hx-activity-table",
        poll_interval_seconds=60,
        loading_key="activity",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "activity_fragment": activity_fragment,
        "operations_url": "/ui/operations",
    }


def _format_activity_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str | int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _build_activity_rows(items: Sequence[Mapping[str, Any]]) -> Sequence[TableRow]:
    rows: list[TableRow] = []
    for item in items:
        timestamp = _format_activity_cell(item.get("timestamp", ""))
        action_type = _format_activity_cell(item.get("type", ""))
        status = _format_activity_cell(item.get("status", ""))
        details_value = item.get("details")
        details = _format_activity_cell(details_value)
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=timestamp),
                    TableCell(text=action_type),
                    TableCell(text=status),
                    TableCell(text=details or "—"),
                )
            )
        )
    return tuple(rows)


def build_activity_fragment_context(
    request: Request,
    *,
    items: Sequence[Mapping[str, Any]],
    limit: int,
    offset: int,
    total_count: int,
    type_filter: str | None,
    status_filter: str | None,
) -> Mapping[str, Any]:
    rows = _build_activity_rows(items)
    table = TableDefinition(
        identifier="activity-table",
        column_keys=(
            "activity.timestamp",
            "activity.type",
            "activity.status",
            "activity.details",
        ),
        rows=rows,
        caption_key="activity.table.caption",
    )

    data_attributes: dict[str, str] = {
        "total": str(total_count),
        "limit": str(limit),
        "offset": str(offset),
    }
    if type_filter:
        data_attributes["type"] = type_filter
    if status_filter:
        data_attributes["status"] = status_filter

    try:
        base_url = request.url_for("activity_table")
    except Exception:
        base_url = "/ui/activity/table"
    filters: list[tuple[str, str]] = []
    if type_filter:
        filters.append(("type", type_filter))
    if status_filter:
        filters.append(("status", status_filter))

    def _page_url(new_offset: int | None) -> str | None:
        if new_offset is None:
            return None
        query = [("limit", str(limit)), ("offset", str(max(new_offset, 0)))]
        query.extend(filters)
        return f"{base_url}?{urlencode(query)}"

    previous_offset = offset - limit if offset > 0 else None
    next_offset = offset + limit if offset + limit < total_count else None

    pagination = PaginationContext(
        label_key="activity",
        target="#hx-activity-table",
        previous_url=_page_url(previous_offset),
        next_url=_page_url(next_offset),
    )

    fragment = TableFragment(
        identifier="hx-activity-table",
        table=table,
        empty_state_key="activity",
        data_attributes=data_attributes,
        pagination=pagination,
    )

    return {"request": request, "fragment": fragment}


def build_spotify_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="spotify",
        role=session.role,
        navigation=_build_primary_navigation(session, active="spotify"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    try:
        status_url = request.url_for("spotify_status_fragment")
    except Exception:
        status_url = "/ui/spotify/status"
    status_fragment = AsyncFragment(
        identifier="hx-spotify-status",
        url=status_url,
        target="#hx-spotify-status",
        poll_interval_seconds=60,
        swap="innerHTML",
        loading_key="spotify.status",
    )

    try:
        account_url = request.url_for("spotify_account_fragment")
    except Exception:
        account_url = "/ui/spotify/account"
    account_fragment = AsyncFragment(
        identifier="hx-spotify-account",
        url=account_url,
        target="#hx-spotify-account",
        swap="innerHTML",
        loading_key="spotify.account",
    )

    try:
        top_tracks_url = request.url_for("spotify_top_tracks_fragment")
    except Exception:
        top_tracks_url = "/ui/spotify/top/tracks"
    top_tracks_fragment = AsyncFragment(
        identifier="hx-spotify-top-tracks",
        url=top_tracks_url,
        target="#hx-spotify-top-tracks",
        swap="innerHTML",
        loading_key="spotify.top_tracks",
    )

    try:
        top_artists_url = request.url_for("spotify_top_artists_fragment")
    except Exception:
        top_artists_url = "/ui/spotify/top/artists"
    top_artists_fragment = AsyncFragment(
        identifier="hx-spotify-top-artists",
        url=top_artists_url,
        target="#hx-spotify-top-artists",
        swap="innerHTML",
        loading_key="spotify.top_artists",
    )

    try:
        recommendations_url = request.url_for("spotify_recommendations_fragment")
    except Exception:
        recommendations_url = "/ui/spotify/recommendations"
    recommendations_fragment = AsyncFragment(
        identifier="hx-spotify-recommendations",
        url=recommendations_url,
        target="#hx-spotify-recommendations",
        swap="innerHTML",
        loading_key="spotify.recommendations",
    )

    try:
        saved_url = request.url_for("spotify_saved_tracks_fragment")
    except Exception:
        saved_url = "/ui/spotify/saved"
    saved_fragment = AsyncFragment(
        identifier="hx-spotify-saved",
        url=saved_url,
        target="#hx-spotify-saved",
        swap="innerHTML",
        loading_key="spotify.saved_tracks",
    )

    try:
        playlists_url = request.url_for("spotify_playlists_fragment")
    except Exception:
        playlists_url = "/ui/spotify/playlists"
    playlists_fragment = AsyncFragment(
        identifier="hx-spotify-playlists",
        url=playlists_url,
        target="#hx-spotify-playlists",
        swap="innerHTML",
        loading_key="spotify.playlists",
    )

    try:
        artists_url = request.url_for("spotify_artists_fragment")
    except Exception:
        artists_url = "/ui/spotify/artists"
    artists_fragment = AsyncFragment(
        identifier="hx-spotify-artists",
        url=artists_url,
        target="#hx-spotify-artists",
        swap="innerHTML",
        loading_key="spotify.artists",
    )

    free_ingest_fragment: AsyncFragment | None = None
    if session.features.imports:
        try:
            free_ingest_url = request.url_for("spotify_free_ingest_fragment")
        except Exception:
            free_ingest_url = "/ui/spotify/free"
        free_ingest_fragment = AsyncFragment(
            identifier="hx-spotify-free-ingest",
            url=free_ingest_url,
            target="#hx-spotify-free-ingest",
            poll_interval_seconds=15,
            swap="innerHTML",
            loading_key="spotify.free_ingest",
        )

    try:
        backfill_url = request.url_for("spotify_backfill_fragment")
    except Exception:
        backfill_url = "/ui/spotify/backfill"
    backfill_fragment = AsyncFragment(
        identifier="hx-spotify-backfill",
        url=backfill_url,
        target="#hx-spotify-backfill",
        poll_interval_seconds=30,
        swap="innerHTML",
        loading_key="spotify.backfill",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "status_fragment": status_fragment,
        "account_fragment": account_fragment,
        "top_tracks_fragment": top_tracks_fragment,
        "top_artists_fragment": top_artists_fragment,
        "recommendations_fragment": recommendations_fragment,
        "saved_fragment": saved_fragment,
        "playlists_fragment": playlists_fragment,
        "artists_fragment": artists_fragment,
        "free_ingest_fragment": free_ingest_fragment,
        "backfill_fragment": backfill_fragment,
    }


def build_search_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="search",
        role=session.role,
        navigation=_build_primary_navigation(session, active="soulseek"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    search_form = _build_search_form(DEFAULT_SOURCES)

    results_url = _safe_url_for(request, "search_results", "/ui/search/results")
    results_fragment = AsyncFragment(
        identifier="hx-search-results",
        url=results_url,
        target="#hx-search-results",
        swap="innerHTML",
        loading_key="search.results",
    )

    queue_fragment: AsyncFragment | None = None
    if session.features.dlq:
        queue_url = _safe_url_for(request, "downloads_table", "/ui/downloads/table")
        # The queue preview is optional context; lazy-load it via the `revealed`
        # trigger so the primary search form stays responsive.
        queue_fragment = AsyncFragment(
            identifier="hx-search-queue",
            url=f"{queue_url}?limit=20",
            target="#hx-search-queue",
            poll_interval_seconds=30,
            swap="innerHTML",
            loading_key="search.queue",
            load_event="revealed",
        )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "search_form": search_form,
        "results_fragment": results_fragment,
        "queue_fragment": queue_fragment,
    }


def build_soulseek_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    soulseek_badge: StatusBadge | None = None,
    suggested_tasks: Sequence[SuggestedTask] = (),
    tasks_completion: int = 0,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="soulseek",
        role=session.role,
        navigation=_build_primary_navigation(
            session,
            active="soulseek",
            soulseek_badge=soulseek_badge,
        ),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    status_url = _safe_url_for(request, "soulseek_status_fragment", "/ui/soulseek/status")
    status_fragment = AsyncFragment(
        identifier="hx-soulseek-status",
        url=status_url,
        target="#hx-soulseek-status",
        poll_interval_seconds=60,
        loading_key="soulseek.status",
    )

    configuration_url = _safe_url_for(
        request, "soulseek_configuration_fragment", "/ui/soulseek/configuration"
    )
    configuration_fragment = AsyncFragment(
        identifier="hx-soulseek-configuration",
        url=configuration_url,
        target="#hx-soulseek-configuration",
        loading_key="soulseek.configuration",
    )

    uploads_url = _safe_url_for(request, "soulseek_uploads_fragment", "/ui/soulseek/uploads")
    uploads_fragment = AsyncFragment(
        identifier="hx-soulseek-uploads",
        url=uploads_url,
        target="#hx-soulseek-uploads",
        poll_interval_seconds=30,
        loading_key="soulseek.uploads",
    )

    downloads_url = _safe_url_for(request, "soulseek_downloads_fragment", "/ui/soulseek/downloads")
    downloads_fragment = AsyncFragment(
        identifier="hx-soulseek-downloads",
        url=downloads_url,
        target="#hx-soulseek-downloads",
        poll_interval_seconds=30,
        loading_key="soulseek.downloads",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "status_fragment": status_fragment,
        "configuration_fragment": configuration_fragment,
        "uploads_fragment": uploads_fragment,
        "downloads_fragment": downloads_fragment,
        "suggested_tasks": tuple(suggested_tasks),
        "tasks_completion": tasks_completion,
    }


def build_soulseek_status_context(
    request: Request,
    *,
    status: StatusResponse,
    health: IntegrationHealth,
    layout: LayoutContext | None = None,
) -> Mapping[str, Any]:
    connection_badge = _status_badge(
        status=status.status,
        test_id="soulseek-status-connection",
        success_label="soulseek.status.connected",
        degraded_label="soulseek.status.degraded",
        down_label="soulseek.status.disconnected",
        unknown_label="soulseek.status.unknown",
        degrade_is_warning=False,
    )
    integration_badge = _status_badge(
        status=health.overall,
        test_id="soulseek-status-integrations",
        success_label="soulseek.integration.ok",
        degraded_label="soulseek.integration.degraded",
        down_label="soulseek.integration.down",
        unknown_label="soulseek.integration.unknown",
    )

    provider_rows: list[TableRow] = []
    for report in sorted(health.providers, key=lambda entry: (entry.provider or "").lower()):
        provider_name = report.provider or "unknown"
        provider_badge = _status_badge(
            status=report.status,
            test_id=f"soulseek-provider-{provider_name}-status",
            success_label="soulseek.integration.ok",
            degraded_label="soulseek.integration.degraded",
            down_label="soulseek.integration.down",
            unknown_label="soulseek.integration.unknown",
        )
        details_text = _format_health_details(report.details)
        if details_text:
            details_cell = TableCell(text=details_text)
        else:
            details_cell = TableCell(text_key="soulseek.providers.details.none")
        provider_rows.append(
            TableRow(
                cells=(
                    TableCell(text=provider_name),
                    TableCell(badge=provider_badge),
                    details_cell,
                ),
                test_id=f"soulseek-provider-{provider_name}",
            )
        )

    provider_table = TableDefinition(
        identifier="soulseek-providers-table",
        column_keys=(
            "soulseek.providers.name",
            "soulseek.providers.status",
            "soulseek.providers.details",
        ),
        rows=tuple(provider_rows),
        caption_key="soulseek.providers.caption",
    )

    return {
        "request": request,
        "connection_badge": connection_badge,
        "integration_badge": integration_badge,
        "provider_table": provider_table,
        "layout": layout,
    }


def _boolean_badge(
    value: bool,
    *,
    test_id: str,
    highlight_missing: bool = False,
) -> StatusBadge:
    if value:
        return StatusBadge(
            label_key="status.enabled",
            variant="success",
            test_id=test_id,
        )
    return StatusBadge(
        label_key="status.disabled",
        variant="danger" if highlight_missing else "muted",
        test_id=test_id,
    )


def _format_percentage(value: float | None) -> str:
    if value is None:
        return ""
    clamped = max(0.0, min(value, 1.0))
    return f"{clamped * 100.0:.0f}%"


def _format_transfer_size(size: int | None) -> str:
    if size is None or size < 0:
        return ""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for index, unit in enumerate(units):
        if value < 1024.0 or index == len(units) - 1:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return ""


def _format_transfer_speed(speed: float | None) -> str:
    if speed is None or speed < 0:
        return ""
    value = float(speed)
    if value < 1024.0:
        return f"{value:.0f} B/s"
    value /= 1024.0
    if value < 1024.0:
        return f"{value:.1f} KiB/s"
    value /= 1024.0
    return f"{value:.1f} MiB/s"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    trimmed = value.replace(microsecond=0)
    return trimmed.isoformat(sep=" ")


def _summarize_live_metadata(metadata: Mapping[str, Any] | None) -> str:
    if not metadata:
        return ""
    highlights: list[str] = []
    for key in ("status", "progress", "speed", "eta", "peer"):
        if key in metadata:
            highlights.append(f"{key}={metadata[key]}")
    if not highlights:
        for index, (key, value) in enumerate(metadata.items()):
            highlights.append(f"{key}={value}")
            if index >= 2:
                break
    return ", ".join(str(entry) for entry in highlights if entry)


def _soulseek_download_status_badge(status: str) -> StatusBadge:
    normalised = (status or "").strip().lower() or "unknown"
    label_key = f"soulseek.downloads.status.{normalised}"
    test_id = f"soulseek-download-status-{normalised}"
    if normalised in {"queued", "pending", "running", "downloading"}:
        return StatusBadge(label_key=label_key, variant="success", test_id=test_id)
    if normalised in set(SOULSEEK_RETRYABLE_STATES) | {"failed", "dead_letter"}:
        return StatusBadge(label_key=label_key, variant="danger", test_id=test_id)
    return StatusBadge(label_key=label_key, variant="muted", test_id=test_id)


def build_soulseek_config_context(
    request: Request,
    *,
    soulseek_config: SoulseekConfig,
    security_config: SecurityConfig,
) -> Mapping[str, Any]:
    has_api_key = bool((soulseek_config.api_key or "").strip())
    if soulseek_config.preferred_formats:
        preferred_formats = ", ".join(soulseek_config.preferred_formats)
    else:
        preferred_formats = "Any"

    if has_api_key:
        api_key_cell = TableCell(
            text_key="soulseek.config.api_key_set",
            test_id="soulseek-config-api-key",
        )
    else:
        api_key_cell = TableCell(
            badge=StatusBadge(
                label_key="soulseek.config.api_key_missing",
                variant="danger",
                test_id="soulseek-config-api-key",
            )
        )

    rows = [
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.base_url"),
                TableCell(text=soulseek_config.base_url),
            ),
            test_id="soulseek-config-base-url",
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.api_key"),
                api_key_cell,
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.timeout"),
                TableCell(text=f"{soulseek_config.timeout_ms} ms"),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.retry_max"),
                TableCell(text=str(soulseek_config.retry_max)),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.retry_backoff"),
                TableCell(text=f"{soulseek_config.retry_backoff_base_ms} ms"),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.retry_jitter"),
                TableCell(text=f"{soulseek_config.retry_jitter_pct}%"),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.preferred_formats"),
                TableCell(text=preferred_formats),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.max_results"),
                TableCell(text=str(soulseek_config.max_results)),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.security_profile"),
                TableCell(text=security_config.profile),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.require_auth"),
                TableCell(
                    badge=_boolean_badge(
                        security_config.require_auth,
                        test_id="soulseek-config-require-auth",
                    )
                ),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.rate_limiting"),
                TableCell(
                    badge=_boolean_badge(
                        security_config.rate_limiting_enabled,
                        test_id="soulseek-config-rate-limiting",
                    )
                ),
            ),
        ),
    ]

    table = TableDefinition(
        identifier="soulseek-config-table",
        column_keys=("soulseek.config.setting", "soulseek.config.value"),
        rows=tuple(rows),
        caption_key="soulseek.config.caption",
    )

    return {
        "request": request,
        "table": table,
    }


def build_soulseek_uploads_context(
    request: Request,
    *,
    uploads: Sequence[SoulseekUploadRow],
    csrf_token: str,
    include_all: bool,
    session: UiSession,
) -> Mapping[str, Any]:
    can_manage_uploads = session.allows("admin")
    rows: list[TableRow] = []
    cancel_url = _safe_url_for(
        request,
        "soulseek_upload_cancel",
        "/ui/soulseek/uploads/cancel",
    )
    target = "#hx-soulseek-uploads"
    for upload in uploads:
        hidden_fields = {
            "csrftoken": csrf_token,
            "upload_id": upload.identifier,
        }
        if include_all:
            hidden_fields["scope"] = "all"
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=upload.identifier),
                    TableCell(text=upload.username or ""),
                    TableCell(text=upload.filename),
                    TableCell(text=upload.status),
                    TableCell(text=_format_percentage(upload.progress)),
                    TableCell(text=_format_transfer_size(upload.size_bytes)),
                    TableCell(text=_format_transfer_speed(upload.speed_bps)),
                    TableCell(
                        form=TableCellForm(
                            action=cancel_url,
                            method="post",
                            submit_label_key="soulseek.uploads.cancel",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap="outerHTML",
                            disabled=not can_manage_uploads,
                            test_id="soulseek-upload-cancel",
                        )
                    ),
                ),
                test_id=f"soulseek-upload-{upload.identifier}",
            )
        )

    table = TableDefinition(
        identifier="soulseek-uploads-table",
        column_keys=(
            "soulseek.uploads.id",
            "soulseek.uploads.user",
            "soulseek.uploads.filename",
            "soulseek.uploads.status",
            "soulseek.uploads.progress",
            "soulseek.uploads.size",
            "soulseek.uploads.speed",
            "soulseek.uploads.actions",
        ),
        rows=tuple(rows),
        caption_key="soulseek.uploads.caption",
    )

    base_url = _safe_url_for(
        request,
        "soulseek_uploads_fragment",
        "/ui/soulseek/uploads",
    )
    refresh_url = f"{base_url}?all=1" if include_all else base_url
    cleanup_url = _safe_url_for(
        request,
        "soulseek_uploads_cleanup",
        "/ui/soulseek/uploads/cleanup",
    )

    fragment = TableFragment(
        identifier="hx-soulseek-uploads",
        table=table,
        empty_state_key="soulseek.uploads",
        data_attributes={
            "count": str(len(rows)),
            "scope": "all" if include_all else "active",
            "refresh-url": refresh_url,
        },
    )

    return {
        "request": request,
        "fragment": fragment,
        "csrf_token": csrf_token,
        "include_all": include_all,
        "refresh_url": refresh_url,
        "active_url": base_url,
        "all_url": f"{base_url}?all=1",
        "cleanup_url": cleanup_url,
        "cleanup_target": target,
        "cleanup_swap": "outerHTML",
        "cleanup_disabled": not can_manage_uploads,
        "can_manage_uploads": can_manage_uploads,
    }


def build_soulseek_downloads_context(
    request: Request,
    *,
    page: DownloadPage,
    csrf_token: str,
    include_all: bool,
    session: UiSession,
) -> Mapping[str, Any]:
    scope_value = "all" if include_all else "active"
    retryable_states = set(SOULSEEK_RETRYABLE_STATES)
    target = "#hx-soulseek-downloads"
    can_manage_downloads = session.allows("admin")
    modal_target = "#modal-root"
    modal_swap = "innerHTML"
    action_swap = "outerHTML"

    lyrics_view_base = _download_action_base_url(
        request,
        "soulseek_download_lyrics",
        "/ui/soulseek/download/{download_id}/lyrics",
    )
    lyrics_refresh_base = _download_action_base_url(
        request,
        "refresh_download_lyrics",
        "/ui/soulseek/download/{download_id}/lyrics/refresh",
    )
    metadata_view_base = _download_action_base_url(
        request,
        "soulseek_download_metadata",
        "/ui/soulseek/download/{download_id}/metadata",
    )
    metadata_refresh_base = _download_action_base_url(
        request,
        "refresh_download_metadata",
        "/ui/soulseek/download/{download_id}/metadata/refresh",
    )
    artwork_view_base = _download_action_base_url(
        request,
        "soulseek_download_artwork",
        "/ui/soulseek/download/{download_id}/artwork",
    )
    artwork_refresh_base = _download_action_base_url(
        request,
        "soulseek_refresh_artwork",
        "/ui/soulseek/download/{download_id}/artwork/refresh",
    )

    rows: list[TableRow] = []
    for entry in page.items:
        try:
            requeue_url = request.url_for(
                "soulseek_download_requeue", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            requeue_url = f"/ui/soulseek/downloads/{entry.identifier}/requeue"
        try:
            cancel_url = request.url_for(
                "soulseek_download_cancel", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            cancel_url = f"/ui/soulseek/download/{entry.identifier}"

        try:
            lyrics_view_url = request.url_for(
                "soulseek_download_lyrics", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            lyrics_view_url = f"/ui/soulseek/download/{entry.identifier}/lyrics"
        try:
            lyrics_refresh_url = request.url_for(
                "refresh_download_lyrics", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            lyrics_refresh_url = f"/ui/soulseek/download/{entry.identifier}/lyrics/refresh"

        try:
            metadata_view_url = request.url_for(
                "soulseek_download_metadata", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            metadata_view_url = f"/ui/soulseek/download/{entry.identifier}/metadata"
        try:
            metadata_refresh_url = request.url_for(
                "refresh_download_metadata", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            metadata_refresh_url = (
                f"/ui/soulseek/download/{entry.identifier}/metadata/refresh"
            )

        try:
            artwork_view_url = request.url_for(
                "soulseek_download_artwork", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            artwork_view_url = f"/ui/soulseek/download/{entry.identifier}/artwork"
        try:
            artwork_refresh_url = request.url_for(
                "soulseek_refresh_artwork", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            artwork_refresh_url = (
                f"/ui/soulseek/download/{entry.identifier}/artwork/refresh"
            )

        hidden_fields = {
            "csrftoken": csrf_token,
            "scope": scope_value,
            "limit": str(page.limit),
            "offset": str(page.offset),
        }
        can_requeue = (entry.status or "").lower() in retryable_states
        lyrics_status = (entry.lyrics_status or "").strip().lower()
        artwork_status = (entry.artwork_status or "").strip().lower()
        lyrics_pending = lyrics_status in {"pending", "running", "processing", "queued"}
        artwork_pending = artwork_status in {"pending", "running", "processing", "queued"}
        lyrics_view_disabled = not (entry.has_lyrics and entry.lyrics_path)
        lyrics_refresh_disabled = (not can_manage_downloads) or lyrics_pending
        metadata_view_disabled = entry.organized_path is None
        metadata_refresh_disabled = not can_manage_downloads
        artwork_view_disabled = not (entry.has_artwork and entry.artwork_path)
        artwork_refresh_disabled = (not can_manage_downloads) or artwork_pending

        lyrics_view_form = TableCellForm(
            action=lyrics_view_url,
            method="get",
            submit_label_key="soulseek.downloads.lyrics.view",
            hx_target=modal_target,
            hx_swap=modal_swap,
            hx_method="get",
            disabled=lyrics_view_disabled,
            test_id=f"soulseek-download-lyrics-view-{entry.identifier}",
        )
        lyrics_refresh_form = TableCellForm(
            action=lyrics_refresh_url,
            method="post",
            submit_label_key="soulseek.downloads.lyrics.refresh",
            hidden_fields=hidden_fields,
            hx_target=target,
            hx_swap=action_swap,
            disabled=lyrics_refresh_disabled,
            test_id=f"soulseek-download-lyrics-refresh-{entry.identifier}",
        )

        metadata_view_form = TableCellForm(
            action=metadata_view_url,
            method="get",
            submit_label_key="soulseek.downloads.metadata.view",
            hx_target=modal_target,
            hx_swap=modal_swap,
            hx_method="get",
            disabled=metadata_view_disabled,
            test_id=f"soulseek-download-metadata-view-{entry.identifier}",
        )
        metadata_refresh_form = TableCellForm(
            action=metadata_refresh_url,
            method="post",
            submit_label_key="soulseek.downloads.metadata.refresh",
            hidden_fields=hidden_fields,
            hx_target=target,
            hx_swap=action_swap,
            disabled=metadata_refresh_disabled,
            test_id=f"soulseek-download-metadata-refresh-{entry.identifier}",
        )

        artwork_view_form = TableCellForm(
            action=artwork_view_url,
            method="get",
            submit_label_key="soulseek.downloads.artwork.view",
            hx_target=modal_target,
            hx_swap=modal_swap,
            hx_method="get",
            disabled=artwork_view_disabled,
            test_id=f"soulseek-download-artwork-view-{entry.identifier}",
        )
        artwork_refresh_form = TableCellForm(
            action=artwork_refresh_url,
            method="post",
            submit_label_key="soulseek.downloads.artwork.refresh",
            hidden_fields=hidden_fields,
            hx_target=target,
            hx_swap=action_swap,
            disabled=artwork_refresh_disabled,
            test_id=f"soulseek-download-artwork-refresh-{entry.identifier}",
        )

        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(entry.identifier)),
                    TableCell(text=entry.filename),
                    TableCell(badge=_soulseek_download_status_badge(entry.status)),
                    TableCell(text=_format_percentage(entry.progress)),
                    TableCell(text=str(entry.priority)),
                    TableCell(text=entry.username or ""),
                    TableCell(text=str(entry.retry_count)),
                    TableCell(text=_format_datetime(entry.next_retry_at)),
                    TableCell(text=entry.last_error or ""),
                    TableCell(text=_summarize_live_metadata(entry.live_queue)),
                    TableCell(
                        forms=(lyrics_view_form, lyrics_refresh_form),
                        test_id=f"soulseek-download-lyrics-actions-{entry.identifier}",
                    ),
                    TableCell(
                        forms=(metadata_view_form, metadata_refresh_form),
                        test_id=f"soulseek-download-metadata-actions-{entry.identifier}",
                    ),
                    TableCell(
                        forms=(artwork_view_form, artwork_refresh_form),
                        test_id=f"soulseek-download-artwork-actions-{entry.identifier}",
                    ),
                    TableCell(
                        form=TableCellForm(
                            action=requeue_url,
                            method="post",
                            submit_label_key="soulseek.downloads.requeue",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap=action_swap,
                            disabled=not (can_manage_downloads and can_requeue),
                            test_id="soulseek-download-requeue",
                        )
                    ),
                    TableCell(
                        form=TableCellForm(
                            action=cancel_url,
                            method="post",
                            submit_label_key="soulseek.downloads.cancel",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap=action_swap,
                            hx_method="delete",
                            disabled=not can_manage_downloads,
                            test_id="soulseek-download-cancel",
                        )
                    ),
                ),
                test_id=f"soulseek-download-{entry.identifier}",
            )
        )

    table = TableDefinition(
        identifier="soulseek-downloads-table",
        column_keys=(
            "downloads.id",
            "downloads.filename",
            "downloads.status",
            "downloads.progress",
            "downloads.priority",
            "downloads.user",
            "soulseek.downloads.retry_count",
            "soulseek.downloads.next_retry",
            "soulseek.downloads.last_error",
            "soulseek.downloads.live",
            "soulseek.downloads.lyrics",
            "soulseek.downloads.metadata",
            "soulseek.downloads.artwork",
            "soulseek.downloads.requeue",
            "soulseek.downloads.cancel",
        ),
        rows=tuple(rows),
        caption_key="downloads.table.caption",
    )

    base_url = _safe_url_for(
        request,
        "soulseek_downloads_fragment",
        "/ui/soulseek/downloads",
    )

    def _url_for_scope(all_scope: bool) -> str:
        query = [("limit", str(page.limit)), ("offset", str(page.offset))]
        if all_scope:
            query.append(("all", "1"))
        return f"{base_url}?{urlencode(query)}"

    refresh_url = _url_for_scope(include_all)
    cleanup_url = _safe_url_for(
        request,
        "soulseek_downloads_cleanup",
        "/ui/soulseek/downloads/cleanup",
    )

    def _page_url(new_offset: int) -> str:
        query = [("limit", str(page.limit)), ("offset", str(max(new_offset, 0)))]
        if include_all:
            query.append(("all", "1"))
        return f"{base_url}?{urlencode(query)}"

    previous_url = _page_url(page.offset - page.limit) if page.has_previous else None
    next_url = _page_url(page.offset + page.limit) if page.has_next else None

    pagination: PaginationContext | None = None
    if previous_url or next_url:
        pagination = PaginationContext(
            label_key="downloads",
            target=target,
            previous_url=previous_url,
            next_url=next_url,
        )

    fragment = TableFragment(
        identifier="hx-soulseek-downloads",
        table=table,
        empty_state_key="soulseek.downloads",
        data_attributes={
            "count": str(len(rows)),
            "limit": str(page.limit),
            "offset": str(page.offset),
            "scope": scope_value,
            "refresh-url": refresh_url,
            "modal-target": modal_target,
            "modal-swap": modal_swap,
            "action-target": target,
            "action-swap": action_swap,
            "lyrics-view-base": lyrics_view_base,
            "lyrics-refresh-base": lyrics_refresh_base,
            "metadata-view-base": metadata_view_base,
            "metadata-refresh-base": metadata_refresh_base,
            "artwork-view-base": artwork_view_base,
            "artwork-refresh-base": artwork_refresh_base,
        },
        pagination=pagination,
    )

    return {
        "request": request,
        "fragment": fragment,
        "csrf_token": csrf_token,
        "include_all": include_all,
        "refresh_url": refresh_url,
        "active_url": _url_for_scope(False),
        "all_url": _url_for_scope(True),
        "cleanup_url": cleanup_url,
        "cleanup_target": pagination.target if pagination else target,
        "cleanup_swap": pagination.swap if pagination else "outerHTML",
        "cleanup_disabled": not can_manage_downloads,
        "can_manage_downloads": can_manage_downloads,
    }


SPOTIFY_RUNBOOK_URL = "/docs/operations/runbooks/hdm.md"


def build_spotify_status_context(
    request: Request,
    *,
    status: SpotifyStatus,
    oauth: SpotifyOAuthHealth,
    manual_form: FormDefinition,
    csrf_token: str,
    manual_result: SpotifyManualResult | None = None,
    manual_redirect_url: str | None = None,
) -> Mapping[str, Any]:
    alerts: list[AlertMessage] = []
    if manual_result is not None:
        message = (manual_result.message or "").strip()
        if manual_result.ok:
            if not message:
                message = "Spotify authorization completed successfully."
            alerts.append(AlertMessage(level="success", text=message))
        else:
            if not message:
                message = "Manual completion failed. Check the redirect URL and try again."
            alerts.append(AlertMessage(level="error", text=message))

    badges: list[StatusBadge] = []
    badges.append(
        StatusBadge(
            label_key="status.enabled" if status.free_available else "status.disabled",
            variant="success" if status.free_available else "muted",
            test_id="spotify-status-free",
        )
    )
    badges.append(
        StatusBadge(
            label_key="status.enabled" if status.pro_available else "status.disabled",
            variant="success" if status.pro_available else "muted",
            test_id="spotify-status-pro",
        )
    )
    badges.append(
        StatusBadge(
            label_key="status.enabled" if status.authenticated else "status.disabled",
            variant="success" if status.authenticated else "danger",
            test_id="spotify-status-auth",
        )
    )

    status_label_key = (
        f"spotify.status.{status.status}" if status.status else "spotify.status.unconfigured"
    )

    return {
        "request": request,
        "status": status,
        "oauth": oauth,
        "badges": tuple(badges),
        "alert_messages": tuple(alerts),
        "manual_form": manual_form,
        "csrf_token": csrf_token,
        "status_label_key": status_label_key,
        "manual_redirect_url": manual_redirect_url,
        "runbook_url": SPOTIFY_RUNBOOK_URL,
    }


def build_spotify_account_context(
    request: Request,
    *,
    account: SpotifyAccountSummary | None,
    csrf_token: str,
    refresh_action: str,
    show_refresh: bool,
    show_reset: bool,
    reset_action: str | None,
) -> Mapping[str, Any]:
    alerts: tuple[AlertMessage, ...] = ()
    base_context = {
        "request": request,
        "alert_messages": alerts,
        "csrf_token": csrf_token,
        "refresh_action": refresh_action,
        "show_refresh": show_refresh,
        "show_reset": show_reset,
        "reset_action": reset_action,
    }
    if account is None:
        return {
            **base_context,
            "has_account": False,
            "summary": None,
            "fields": (),
        }

    product_text = account.product or "—"
    followers_text = f"{account.followers:,}" if account.followers else "0"
    country_text = account.country or "—"
    email_text = account.email or "—"

    fields: tuple[DefinitionItem, ...] = (
        DefinitionItem(
            label_key="spotify.account.display_name",
            value=account.display_name,
            test_id="spotify-account-display-name",
        ),
        DefinitionItem(
            label_key="spotify.account.email",
            value=email_text,
            test_id="spotify-account-email",
            is_missing=account.email is None,
        ),
        DefinitionItem(
            label_key="spotify.account.product",
            value=product_text,
            test_id="spotify-account-product",
        ),
        DefinitionItem(
            label_key="spotify.account.followers",
            value=followers_text,
            test_id="spotify-account-followers",
        ),
        DefinitionItem(
            label_key="spotify.account.country",
            value=country_text,
            test_id="spotify-account-country",
        ),
    )

    return {
        **base_context,
        "has_account": True,
        "summary": account,
        "fields": fields,
    }


def _build_spotify_top_context(
    request: Request,
    *,
    fragment_id: str,
    table_identifier: str,
    column_keys: Sequence[str],
    rows: Sequence[TableRow],
    caption_key: str,
    empty_state_key: str,
    time_range: str | None = None,
    time_range_options: Sequence[SpotifyTimeRangeOption] | None = None,
) -> Mapping[str, Any]:
    table = TableDefinition(
        identifier=table_identifier,
        column_keys=tuple(column_keys),
        rows=tuple(rows),
        caption_key=caption_key,
    )

    fragment = TableFragment(
        identifier=fragment_id,
        table=table,
        empty_state_key=empty_state_key,
        data_attributes={"count": str(len(rows))},
    )
    context: dict[str, Any] = {"request": request, "fragment": fragment}
    if time_range_options is not None:
        context["time_range"] = time_range
        context["time_range_options"] = tuple(time_range_options)
    return context


def build_spotify_top_tracks_context(
    request: Request,
    *,
    tracks: Sequence[SpotifyTopTrackRow],
    csrf_token: str,
    limit: int,
    offset: int,
    time_range: str,
) -> Mapping[str, Any]:
    def _format_duration(duration_ms: int | None) -> str:
        if duration_ms is None or duration_ms < 0:
            return ""
        total_seconds = duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    try:
        save_url = request.url_for("spotify_saved_tracks_action", action="save")
    except Exception:  # pragma: no cover - fallback for tests
        save_url = "/ui/spotify/saved/save"

    rows: list[TableRow] = []
    for track in tracks:
        artists_text = ", ".join(track.artists)
        duration_text = _format_duration(track.duration_ms)
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=track.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{track.identifier}"
                if track.identifier
                else "/ui/spotify/tracks"
            )
        detail_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        save_form = TableCellForm(
            action=save_url,
            method="post",
            submit_label_key="spotify.saved.save",
            hidden_fields={
                "csrftoken": csrf_token,
                "track_id": track.identifier,
                "limit": str(limit),
                "offset": str(offset),
            },
            hx_target="#hx-spotify-saved",
            hx_swap="outerHTML",
            disabled=not bool(track.identifier),
            test_id=(
                f"spotify-top-track-save-{track.identifier}"
                if track.identifier
                else "spotify-top-track-save"
            ),
        )
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(track.rank)),
                    TableCell(text=track.name),
                    TableCell(text=artists_text),
                    TableCell(text=track.album or ""),
                    TableCell(text=str(track.popularity)),
                    TableCell(text=duration_text),
                    _build_external_link_cell(
                        track.external_url,
                        cell_test_id=(
                            f"spotify-top-track-link-cell-{track.identifier}"
                            if track.identifier
                            else "spotify-top-track-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-top-track-link-{track.identifier}"
                            if track.identifier
                            else "spotify-top-track-link"
                        ),
                        label="Spotify",
                        aria_label=(
                            f"Open {track.name} on Spotify" if track.name else "Open in Spotify"
                        ),
                    ),
                    TableCell(
                        forms=(detail_form, save_form),
                        test_id=(
                            f"spotify-top-track-actions-{track.identifier}"
                            if track.identifier
                            else "spotify-top-track-actions"
                        ),
                    ),
                ),
                test_id=f"spotify-top-track-{track.identifier}",
            )
        )

    return _build_spotify_top_context(
        request,
        fragment_id="hx-spotify-top-tracks",
        table_identifier="spotify-top-tracks-table",
        column_keys=(
            "spotify.top_tracks.rank",
            "spotify.top_tracks.name",
            "spotify.top_tracks.artists",
            "spotify.top_tracks.album",
            "spotify.top_tracks.popularity",
            "spotify.top_tracks.duration",
            "spotify.top_tracks.link",
            "spotify.top_tracks.actions",
        ),
        rows=rows,
        caption_key="spotify.top_tracks.caption",
        empty_state_key="spotify.top_tracks",
        time_range=time_range,
        time_range_options=_build_time_range_options(
            request,
            endpoint_name="spotify_top_tracks_fragment",
            fragment_id="hx-spotify-top-tracks",
            selected=time_range,
            fallback_path="/ui/spotify/top/tracks",
        ),
    )


def build_spotify_top_artists_context(
    request: Request,
    *,
    artists: Sequence[SpotifyTopArtistRow],
    time_range: str,
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for artist in artists:
        genres_text = ", ".join(artist.genres)
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(artist.rank)),
                    TableCell(text=artist.name),
                    _build_external_link_cell(
                        artist.external_url,
                        cell_test_id=(
                            f"spotify-top-artist-link-cell-{artist.identifier}"
                            if artist.identifier
                            else "spotify-top-artist-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-top-artist-link-{artist.identifier}"
                            if artist.identifier
                            else "spotify-top-artist-link"
                        ),
                        label="Spotify",
                        aria_label=(
                            f"Open {artist.name} on Spotify" if artist.name else "Open in Spotify"
                        ),
                    ),
                    TableCell(text=f"{artist.followers:,}" if artist.followers else "0"),
                    TableCell(text=str(artist.popularity)),
                    TableCell(text=genres_text),
                ),
                test_id=f"spotify-top-artist-{artist.identifier}",
            )
        )

    return _build_spotify_top_context(
        request,
        fragment_id="hx-spotify-top-artists",
        table_identifier="spotify-top-artists-table",
        column_keys=(
            "spotify.top_artists.rank",
            "spotify.top_artists.name",
            "spotify.top_artists.link",
            "spotify.top_artists.followers",
            "spotify.top_artists.popularity",
            "spotify.top_artists.genres",
        ),
        rows=rows,
        caption_key="spotify.top_artists.caption",
        empty_state_key="spotify.top_artists",
        time_range=time_range,
        time_range_options=_build_time_range_options(
            request,
            endpoint_name="spotify_top_artists_fragment",
            fragment_id="hx-spotify-top-artists",
            selected=time_range,
            fallback_path="/ui/spotify/top/artists",
        ),
    )


def build_spotify_playlists_context(
    request: Request,
    *,
    playlists: Sequence[SpotifyPlaylistRow],
    csrf_token: str,
    filter_action: str,
    refresh_url: str,
    table_target: str,
    owner_options: Sequence[SpotifyPlaylistFilterOption],
    sync_status_options: Sequence[SpotifyPlaylistFilterOption],
    owner_filter: str | None = None,
    status_filter: str | None = None,
    force_sync_url: str | None = None,
) -> Mapping[str, Any]:
    default_limit = 25
    rows: list[TableRow] = []
    for playlist in playlists:
        try:
            items_url = request.url_for(
                "spotify_playlist_items_fragment", playlist_id=playlist.identifier
            )
        except Exception:  # pragma: no cover - fallback for tests
            items_url = f"/ui/spotify/playlists/{playlist.identifier}/tracks"

        hidden_fields: dict[str, str] = {
            "limit": str(default_limit),
            "offset": "0",
        }
        if playlist.name:
            hidden_fields["name"] = playlist.name

        action_form = TableCellForm(
            action=items_url,
            method="get",
            submit_label_key="spotify.playlists.view_tracks",
            hidden_fields=hidden_fields,
            hx_target="#spotify-playlist-items",
            hx_swap="innerHTML",
            hx_method="get",
        )
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=playlist.name),
                    TableCell(text=playlist.owner or "—"),
                    TableCell(text=str(playlist.track_count)),
                    TableCell(text=str(playlist.follower_count)),
                    TableCell(
                        text=(
                            playlist.sync_status.replace("_", " ").title()
                            if playlist.sync_status
                            else "—"
                        )
                    ),
                    TableCell(text=playlist.updated_at.isoformat()),
                    TableCell(
                        form=action_form,
                        test_id=f"spotify-playlist-view-{playlist.identifier}",
                    ),
                ),
                test_id=f"spotify-playlist-{playlist.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-playlists-table",
        column_keys=(
            "spotify.playlists.name",
            "spotify.playlists.owner",
            "spotify.playlists.tracks",
            "spotify.playlists.followers",
            "spotify.playlists.sync_status",
            "spotify.playlists.updated",
            "spotify.playlists.actions",
        ),
        rows=tuple(rows),
        caption_key="spotify.playlists.caption",
    )

    fragment = TableFragment(
        identifier="hx-spotify-playlists",
        table=table,
        empty_state_key="spotify.playlists",
        data_attributes={"count": str(len(rows))},
    )

    return {
        "request": request,
        "fragment": fragment,
        "playlist_items_target": "#spotify-playlist-items",
        "csrf_token": csrf_token,
        "filter_action": filter_action,
        "refresh_url": refresh_url,
        "force_sync_url": force_sync_url,
        "table_target": table_target,
        "owner_options": tuple(owner_options),
        "sync_status_options": tuple(sync_status_options),
        "owner_filter": owner_filter,
        "status_filter": status_filter,
    }


def build_spotify_playlist_items_context(
    request: Request,
    *,
    playlist_id: str,
    playlist_name: str | None,
    rows: Sequence[SpotifyPlaylistItemRow],
    total_count: int,
    limit: int,
    offset: int,
) -> Mapping[str, Any]:
    table_rows: list[TableRow] = []
    for row in rows:
        artists_text = ", ".join(row.artists)
        added_text = format_datetime_display(row.added_at)
        track_text = row.name if not row.is_local else f"{row.name} (local)"
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=row.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{row.identifier}" if row.identifier else "/ui/spotify/tracks"
            )
        detail_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=track_text),
                    TableCell(text=artists_text),
                    TableCell(text=row.album or ""),
                    TableCell(text=added_text),
                    TableCell(text=row.added_by or ""),
                    TableCell(
                        forms=(detail_form,),
                        test_id=f"spotify-playlist-item-detail-{row.identifier}",
                    ),
                ),
                test_id=f"spotify-playlist-item-{row.identifier}",
            )
        )

    row_count = len(table_rows)

    table = TableDefinition(
        identifier="spotify-playlist-items-table",
        column_keys=(
            "spotify.playlist_items.track",
            "spotify.playlist_items.artists",
            "spotify.playlist_items.album",
            "spotify.playlist_items.added",
            "spotify.playlist_items.added_by",
            "spotify.playlist_items.actions",
        ),
        rows=tuple(table_rows),
        caption_key="spotify.playlist_items.caption",
    )

    try:
        base_url = request.url_for("spotify_playlist_items_fragment", playlist_id=playlist_id)
    except Exception:  # pragma: no cover - fallback for tests
        base_url = f"/ui/spotify/playlists/{playlist_id}/tracks"

    pagination: PaginationContext | None = None
    previous_url: str | None = None
    next_url: str | None = None

    params: dict[str, Any] = {"limit": limit}
    if playlist_name:
        params["name"] = playlist_name

    if offset > 0:
        prev_params = dict(params)
        prev_params["offset"] = max(0, offset - limit)
        previous_url = f"{base_url}?{urlencode(prev_params)}"

    if offset + limit < total_count:
        next_params = dict(params)
        next_params["offset"] = offset + limit
        next_url = f"{base_url}?{urlencode(next_params)}"

    if previous_url or next_url:
        pagination = PaginationContext(
            label_key="spotify.playlist_items",
            target="#spotify-playlist-items",
            swap="innerHTML",
            previous_url=previous_url,
            next_url=next_url,
        )

    fragment = TableFragment(
        identifier="hx-spotify-playlist-items",
        table=table,
        empty_state_key="spotify.playlist_items",
        data_attributes={
            "playlist-id": playlist_id,
            "count": str(row_count),
        },
        pagination=pagination,
    )

    return {
        "request": request,
        "fragment": fragment,
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "page_limit": limit,
        "page_offset": offset,
        "total_count": total_count,
        "row_count": row_count,
    }


def build_spotify_saved_tracks_context(
    request: Request,
    *,
    rows: Sequence[SpotifySavedTrackRow],
    total_count: int,
    limit: int,
    offset: int,
    csrf_token: str,
    queue_enabled: bool = True,
) -> Mapping[str, Any]:
    artists_label = "spotify.saved_tracks.artists"
    try:
        remove_url = request.url_for("spotify_saved_tracks_action", action="remove")
    except Exception:  # pragma: no cover - fallback for tests
        remove_url = "/ui/spotify/saved/remove"

    try:
        save_url = request.url_for("spotify_saved_tracks_action", action="save")
    except Exception:  # pragma: no cover - fallback for tests
        save_url = "/ui/spotify/saved/save"

    queue_url: str | None = None
    if queue_enabled:
        try:
            queue_url = request.url_for("spotify_saved_tracks_action", action="queue")
        except Exception:  # pragma: no cover - fallback for tests
            queue_url = "/ui/spotify/saved/queue"

    table_rows: list[TableRow] = []
    for row in rows:
        artist_text = ", ".join(row.artists)
        added_text = format_datetime_display(row.added_at)
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=row.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{row.identifier}" if row.identifier else "/ui/spotify/tracks"
            )
        view_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        remove_form = TableCellForm(
            action=remove_url,
            method="post",
            submit_label_key="spotify.saved.remove",
            hidden_fields={
                "csrftoken": csrf_token,
                "track_id": row.identifier,
                "limit": str(limit),
                "offset": str(offset),
            },
            hx_target="#hx-spotify-saved",
            hx_swap="outerHTML",
            hx_method="delete",
        )
        queue_form: TableCellForm | None = None
        if queue_url:
            queue_form = TableCellForm(
                action=queue_url,
                method="post",
                submit_label_key="spotify.saved.queue",
                hidden_fields={
                    "csrftoken": csrf_token,
                    "track_id": row.identifier,
                    "limit": str(limit),
                    "offset": str(offset),
                },
                hx_target="#hx-spotify-saved",
                hx_swap="outerHTML",
                hx_method="post",
            )
        forms: list[TableCellForm] = [view_form]
        if queue_form is not None:
            forms.append(queue_form)
        forms.append(remove_form)

        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.name),
                    TableCell(text=artist_text),
                    TableCell(text=row.album or ""),
                    TableCell(text=added_text),
                    TableCell(
                        forms=tuple(forms),
                        test_id=f"spotify-saved-track-actions-{row.identifier}",
                    ),
                ),
                test_id=f"spotify-saved-track-{row.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-saved-tracks-table",
        column_keys=(
            "spotify.saved_tracks.name",
            artists_label,
            "spotify.saved_tracks.album",
            "spotify.saved_tracks.added",
            "spotify.saved_tracks.actions",
        ),
        rows=tuple(table_rows),
        caption_key="spotify.saved_tracks.caption",
    )

    data_attributes = {
        "count": str(len(table_rows)),
        "total": str(total_count),
        "limit": str(limit),
        "offset": str(offset),
        "queue-enabled": "1" if queue_enabled and queue_url else "0",
    }

    try:
        base_url = request.url_for("spotify_saved_tracks_fragment")
    except Exception:  # pragma: no cover - fallback for tests
        base_url = "/ui/spotify/saved"

    def _page_url(new_offset: int | None) -> str | None:
        if new_offset is None:
            return None
        return f"{base_url}?{urlencode({'limit': limit, 'offset': max(new_offset, 0)})}"

    previous_offset = offset - limit if offset > 0 else None
    next_offset = offset + limit if offset + limit < total_count else None

    pagination = PaginationContext(
        label_key="spotify.saved_tracks",
        target="#hx-spotify-saved",
        previous_url=_page_url(previous_offset),
        next_url=_page_url(next_offset),
    )

    fragment = TableFragment(
        identifier="hx-spotify-saved",
        table=table,
        empty_state_key="spotify.saved_tracks",
        data_attributes=data_attributes,
        pagination=pagination,
    )

    return {
        "request": request,
        "fragment": fragment,
        "save_action_url": save_url,
        "queue_action_url": queue_url,
        "csrf_token": csrf_token,
        "page_limit": limit,
        "page_offset": offset,
        "queue_enabled": queue_enabled and queue_url is not None,
    }


def build_spotify_track_detail_context(
    request: Request,
    *,
    track: SpotifyTrackDetail,
) -> Mapping[str, Any]:
    def _format_duration(duration_ms: int | None) -> str | None:
        if duration_ms is None or duration_ms < 0:
            return None
        total_seconds = duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _format_popularity(value: int | None) -> str | None:
        if value is None or value < 0:
            return None
        return f"{value:,}"

    def _format_percentage(value: object) -> str | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric < 0:
            return None
        return f"{numeric * 100:.0f}%"

    def _format_tempo(value: object) -> str | None:
        try:
            tempo = float(value)
        except (TypeError, ValueError):
            return None
        if tempo <= 0:
            return None
        return f"{tempo:.1f} BPM"

    def _format_loudness(value: object) -> str | None:
        try:
            loudness = float(value)
        except (TypeError, ValueError):
            return None
        return f"{loudness:.1f} dB"

    def _format_time_signature(value: object) -> str | None:
        try:
            signature = int(value)
        except (TypeError, ValueError):
            return None
        if signature <= 0:
            return None
        return f"{signature}/4"

    key_lookup = {
        0: "C",
        1: "C♯ / D♭",
        2: "D",
        3: "D♯ / E♭",
        4: "E",
        5: "F",
        6: "F♯ / G♭",
        7: "G",
        8: "G♯ / A♭",
        9: "A",
        10: "A♯ / B♭",
        11: "B",
    }

    metadata_entries: list[dict[str, Any]] = []

    def _append_metadata(
        key: str,
        value: Any,
        *,
        test_suffix: str,
        url: str | None = None,
    ) -> None:
        is_missing = False
        if value is None or (isinstance(value, str) and not value.strip()):
            is_missing = True
        metadata_entries.append(
            {
                "key": key,
                "value": value,
                "is_missing": is_missing,
                "test_id": f"spotify-track-detail-{test_suffix}",
                "url": url,
            }
        )

    artist_summary = ", ".join(track.artists)

    _append_metadata("name", track.name, test_suffix="name")
    _append_metadata("artists", artist_summary, test_suffix="artists")
    _append_metadata("album", track.album, test_suffix="album")
    _append_metadata("release_date", track.release_date, test_suffix="release-date")
    _append_metadata(
        "duration",
        _format_duration(track.duration_ms),
        test_suffix="duration",
    )
    _append_metadata(
        "popularity",
        _format_popularity(track.popularity),
        test_suffix="popularity",
    )
    metadata_entries.append(
        {
            "key": "explicit",
            "value": bool(track.explicit),
            "is_missing": False,
            "test_id": "spotify-track-detail-explicit",
            "url": None,
        }
    )
    _append_metadata(
        "preview_url",
        track.preview_url,
        test_suffix="preview",
        url=track.preview_url,
    )
    _append_metadata(
        "external_url",
        track.external_url,
        test_suffix="external",
        url=track.external_url,
    )

    feature_entries: list[dict[str, Any]] = []
    features_source = track.features if isinstance(track.features, Mapping) else {}

    def _format_key(value: object) -> str | None:
        try:
            key_index = int(value)
        except (TypeError, ValueError):
            return None
        return key_lookup.get(key_index)

    def _format_mode(value: object) -> str | None:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        if numeric == 1:
            return "major"
        if numeric == 0:
            return "minor"
        return None

    feature_specs = (
        ("danceability", _format_percentage),
        ("energy", _format_percentage),
        ("acousticness", _format_percentage),
        ("instrumentalness", _format_percentage),
        ("liveness", _format_percentage),
        ("speechiness", _format_percentage),
        ("valence", _format_percentage),
        ("tempo", _format_tempo),
        ("loudness", _format_loudness),
        ("key", _format_key),
        ("mode", _format_mode),
        ("time_signature", _format_time_signature),
    )

    for key, formatter in feature_specs:
        raw_value = features_source.get(key) if isinstance(features_source, Mapping) else None
        formatted = formatter(raw_value) if formatter else raw_value
        is_missing = formatted is None
        feature_entries.append(
            {
                "key": key,
                "value": formatted,
                "is_missing": is_missing,
                "test_id": f"spotify-track-feature-{key}",
            }
        )

    modal_title = track.name or track.track_id

    return {
        "request": request,
        "modal_id": "spotify-track-detail-modal",
        "track_identifier": track.track_id,
        "track_title": modal_title,
        "artist_summary": artist_summary,
        "metadata_entries": tuple(metadata_entries),
        "has_metadata": any(not entry["is_missing"] for entry in metadata_entries),
        "feature_entries": tuple(feature_entries),
        "features_available": track.features is not None,
        "has_features": any(not entry["is_missing"] for entry in feature_entries),
    }


def build_spotify_recommendations_context(
    request: Request,
    *,
    csrf_token: str,
    rows: Sequence[SpotifyRecommendationRow] = (),
    seeds: Sequence[SpotifyRecommendationSeed] = (),
    limit: int = 25,
    offset: int = 0,
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    alerts: Sequence[AlertMessage] | None = None,
    seed_defaults: Mapping[str, str] | None = None,
    show_admin_controls: bool = False,
    queue_enabled: bool = True,
) -> Mapping[str, Any]:
    values = dict(form_values or {})
    defaults_source = dict(seed_defaults or {})

    def _resolve_default(key: str, fallback: str) -> str:
        value = values.get(key)
        if value not in (None, ""):
            return str(value)
        default_value = defaults_source.get(key)
        if default_value not in (None, ""):
            return str(default_value)
        return fallback

    defaults = {
        "seed_artists": _resolve_default("seed_artists", ""),
        "seed_tracks": _resolve_default("seed_tracks", ""),
        "seed_genres": _resolve_default("seed_genres", ""),
        "limit": _resolve_default("limit", str(limit)),
    }
    errors = {key: value for key, value in (form_errors or {}).items() if value}

    table_rows: list[TableRow] = []
    try:
        save_url = request.url_for("spotify_saved_tracks_action", action="save")
    except Exception:  # pragma: no cover - fallback for tests
        save_url = "/ui/spotify/saved/save"
    queue_url: str | None = None
    if queue_enabled:
        try:
            queue_url = request.url_for("spotify_recommendations_submit")
        except Exception:  # pragma: no cover - fallback for tests
            queue_url = "/ui/spotify/recommendations"
    for row in rows:
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=row.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{row.identifier}" if row.identifier else "/ui/spotify/tracks"
            )
        if row.preview_url:
            preview_html = (
                '<audio controls preload="none" '
                f'data-test="spotify-recommendation-preview-{row.identifier}">'
                f'<source src="{row.preview_url}" type="audio/mpeg" />'
                "Your browser does not support audio playback."
                f' <a href="{row.preview_url}" target="_blank" rel="noopener">'
                "Open preview"
                "</a>."
                "</audio>"
            )
            preview_cell = TableCell(
                html=preview_html,
                test_id=f"spotify-recommendation-preview-cell-{row.identifier}",
            )
        else:
            preview_cell = TableCell(
                text="—",
                test_id=f"spotify-recommendation-preview-cell-{row.identifier}",
            )
        view_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        queue_form: TableCellForm | None = None
        if queue_enabled and queue_url:
            queue_form = TableCellForm(
                action=queue_url,
                method="post",
                submit_label_key="spotify.saved.queue",
                hidden_fields={
                    "csrftoken": csrf_token,
                    "action": "queue",
                    "track_id": row.identifier,
                    "seed_artists": defaults["seed_artists"],
                    "seed_tracks": defaults["seed_tracks"],
                    "seed_genres": defaults["seed_genres"],
                    "limit": defaults["limit"],
                },
                hx_target="#hx-spotify-recommendations",
                hx_swap="outerHTML",
                disabled=not bool(row.identifier),
                test_id=(
                    f"spotify-recommendation-queue-{row.identifier}"
                    if row.identifier
                    else "spotify-recommendation-queue"
                ),
            )
        save_form = TableCellForm(
            action=save_url,
            method="post",
            submit_label_key="spotify.saved.save",
            hidden_fields={
                "csrftoken": csrf_token,
                "track_id": row.identifier,
                "limit": str(limit),
                "offset": str(offset),
            },
            hx_target="#hx-spotify-saved",
            hx_swap="outerHTML",
            disabled=not bool(row.identifier),
            test_id=(
                f"spotify-recommendation-save-{row.identifier}"
                if row.identifier
                else "spotify-recommendation-save"
            ),
        )
        forms: list[TableCellForm] = [view_form]
        if queue_form is not None:
            forms.append(queue_form)
        forms.append(save_form)

        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.name, test_id=f"spotify-reco-track-{row.identifier}"),
                    TableCell(text=", ".join(row.artists)),
                    TableCell(text=row.album or "—"),
                    _build_external_link_cell(
                        row.external_url,
                        cell_test_id=(
                            f"spotify-recommendation-link-cell-{row.identifier}"
                            if row.identifier
                            else "spotify-recommendation-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-recommendation-link-{row.identifier}"
                            if row.identifier
                            else "spotify-recommendation-link"
                        ),
                        label="Spotify",
                        aria_label=(
                            f"Open {row.name} on Spotify" if row.name else "Open in Spotify"
                        ),
                    ),
                    preview_cell,
                    TableCell(
                        forms=tuple(forms),
                        test_id=f"spotify-recommendation-actions-{row.identifier}",
                    ),
                ),
                test_id=f"spotify-recommendation-{row.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-recommendations-table",
        column_keys=(
            "spotify.recommendations.track",
            "spotify.recommendations.artists",
            "spotify.recommendations.album",
            "spotify.recommendations.link",
            "spotify.recommendations.preview",
            "spotify.recommendations.actions",
        ),
        rows=tuple(table_rows),
        caption_key="spotify.recommendations.caption",
    )

    data_attributes = {
        "count": str(len(table_rows)),
        "queue-enabled": "1" if queue_enabled else "0",
    }

    fragment = TableFragment(
        identifier="hx-spotify-recommendations",
        table=table,
        empty_state_key="spotify.recommendations",
        data_attributes=data_attributes,
    )

    return {
        "request": request,
        "csrf_token": csrf_token,
        "form_defaults": defaults,
        "form_errors": errors,
        "alerts": tuple(alerts or ()),
        "fragment": fragment,
        "seeds": tuple(seeds),
        "show_admin_controls": show_admin_controls,
        "seed_defaults": defaults_source,
        "queue_enabled": queue_enabled,
    }


def build_spotify_artists_context(
    request: Request,
    *,
    artists: Sequence[SpotifyArtistRow],
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for artist in artists:
        genres_text = ", ".join(artist.genres)
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=artist.name),
                    _build_external_link_cell(
                        artist.external_url,
                        cell_test_id=(
                            f"spotify-artist-link-cell-{artist.identifier}"
                            if artist.identifier
                            else "spotify-artist-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-artist-link-{artist.identifier}"
                            if artist.identifier
                            else "spotify-artist-link"
                        ),
                        label="Spotify",
                        aria_label=(
                            f"Open {artist.name} on Spotify" if artist.name else "Open in Spotify"
                        ),
                    ),
                    TableCell(text=f"{artist.followers:,}" if artist.followers else "0"),
                    TableCell(text=str(artist.popularity)),
                    TableCell(text=genres_text),
                ),
                test_id=f"spotify-artist-{artist.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-artists-table",
        column_keys=(
            "spotify.artists.name",
            "spotify.artists.link",
            "spotify.artists.followers",
            "spotify.artists.popularity",
            "spotify.artists.genres",
        ),
        rows=tuple(rows),
        caption_key="spotify.artists.caption",
    )

    fragment = TableFragment(
        identifier="hx-spotify-artists",
        table=table,
        empty_state_key="spotify.artists",
        data_attributes={"count": str(len(rows))},
    )

    return {"request": request, "fragment": fragment}


def build_spotify_backfill_context(
    request: Request,
    *,
    snapshot: SpotifyBackfillSnapshot,
    timeline: Sequence["SpotifyBackfillTimelineEntry"] | None = None,
    alert: AlertMessage | None = None,
) -> Mapping[str, Any]:
    alert_messages: tuple[AlertMessage, ...]
    if alert is None:
        alert_messages = tuple()
    else:
        alert_messages = (alert,)
    history = tuple(timeline or ())
    return {
        "request": request,
        "snapshot": snapshot,
        "alert_messages": alert_messages,
        "timeline": history,
    }


def build_spotify_free_ingest_form_context(
    *,
    csrf_token: str,
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    result: SpotifyFreeIngestResult | None = None,
) -> SpotifyFreeIngestFormContext:
    values = {key: value for key, value in (form_values or {}).items()}
    playlist_value = values.get("playlist_links", "")
    tracks_value = values.get("tracks", "")
    errors = {key: value for key, value in (form_errors or {}).items() if value}

    accepted_items: list[DefinitionItem] = []
    skipped_items: list[DefinitionItem] = []
    if result is not None:
        accepted_items = [
            DefinitionItem(
                label_key="spotify.free_ingest.summary.accepted_playlists",
                value=f"{result.accepted.playlists:,}",
            ),
            DefinitionItem(
                label_key="spotify.free_ingest.summary.accepted_tracks",
                value=f"{result.accepted.tracks:,}",
            ),
            DefinitionItem(
                label_key="spotify.free_ingest.summary.accepted_batches",
                value=f"{result.accepted.batches:,}",
            ),
        ]
        skipped_items = [
            DefinitionItem(
                label_key="spotify.free_ingest.summary.skipped_playlists",
                value=f"{result.skipped.playlists:,}",
            ),
            DefinitionItem(
                label_key="spotify.free_ingest.summary.skipped_tracks",
                value=f"{result.skipped.tracks:,}",
            ),
        ]

    return SpotifyFreeIngestFormContext(
        csrf_token=csrf_token,
        playlist_value=playlist_value,
        tracks_value=tracks_value,
        accepted_items=tuple(accepted_items),
        skipped_items=tuple(skipped_items),
        result=result,
        form_errors=errors,
        upload_error=errors.get("upload"),
    )


def build_spotify_free_ingest_status_context(
    *, status: SpotifyFreeIngestJobSnapshot | None
) -> SpotifyFreeIngestJobContext | None:
    if status is None:
        return None

    counts = (
        DefinitionItem(
            label_key="spotify.free_ingest.status.registered",
            value=f"{status.counts.registered:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.normalized",
            value=f"{status.counts.normalized:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.queued",
            value=f"{status.counts.queued:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.completed",
            value=f"{status.counts.completed:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.failed",
            value=f"{status.counts.failed:,}",
        ),
    )

    accepted_items = (
        DefinitionItem(
            label_key="spotify.free_ingest.summary.accepted_playlists",
            value=f"{status.accepted.playlists:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.summary.accepted_tracks",
            value=f"{status.accepted.tracks:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.summary.accepted_batches",
            value=f"{status.accepted.batches:,}",
        ),
    )

    skipped_items = (
        DefinitionItem(
            label_key="spotify.free_ingest.summary.skipped_playlists",
            value=f"{status.skipped.playlists:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.summary.skipped_tracks",
            value=f"{status.skipped.tracks:,}",
        ),
    )

    return SpotifyFreeIngestJobContext(
        job_id=status.job_id,
        state=status.state,
        counts=counts,
        accepted_items=accepted_items,
        skipped_items=skipped_items,
        queued_tracks=status.queued_tracks,
        failed_tracks=status.failed_tracks,
        skipped_tracks=status.skipped_tracks,
        error=status.error,
        skip_reason=status.skip_reason,
    )


def build_spotify_free_ingest_context(
    request: Request,
    *,
    csrf_token: str,
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    result: SpotifyFreeIngestResult | None = None,
    job_status: SpotifyFreeIngestJobSnapshot | None = None,
    alerts: Sequence[AlertMessage] | None = None,
) -> Mapping[str, Any]:
    form = build_spotify_free_ingest_form_context(
        csrf_token=csrf_token,
        form_values=form_values,
        form_errors=form_errors,
        result=result,
    )
    status_context = build_spotify_free_ingest_status_context(status=job_status)
    return {
        "request": request,
        "alert_messages": tuple(alerts or ()),
        "form": form,
        "job_status": status_context,
    }


def build_watchlist_fragment_context(
    request: Request,
    *,
    entries: Sequence[WatchlistRow],
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for entry in entries:
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=entry.artist_key),
                    TableCell(text=str(entry.priority)),
                    TableCell(text_key=entry.state_key),
                )
            )
        )

    table = TableDefinition(
        identifier="watchlist-table",
        column_keys=(
            "watchlist.artist",
            "watchlist.priority",
            "watchlist.state",
        ),
        rows=tuple(rows),
        caption_key="watchlist.table.caption",
    )

    fragment = TableFragment(
        identifier="hx-watchlist-table",
        table=table,
        empty_state_key="watchlist",
        data_attributes={"count": str(len(rows))},
    )

    return {"request": request, "fragment": fragment}


def build_downloads_fragment_context(
    request: Request,
    *,
    page: DownloadPage,
    status_filter: str | None = None,
    include_all: bool = False,
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for entry in page.items:
        progress = ""
        if entry.progress is not None:
            progress = f"{entry.progress * 100:.0f}%"
        updated_at = entry.updated_at.isoformat() if entry.updated_at else ""
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(entry.identifier)),
                    TableCell(text=entry.filename),
                    TableCell(text=entry.status),
                    TableCell(text=progress),
                    TableCell(text=str(entry.priority)),
                    TableCell(text=entry.username or ""),
                    TableCell(text=updated_at),
                )
            )
        )

    table = TableDefinition(
        identifier="downloads-table",
        column_keys=(
            "downloads.id",
            "downloads.filename",
            "downloads.status",
            "downloads.progress",
            "downloads.priority",
            "downloads.user",
            "downloads.updated",
        ),
        rows=tuple(rows),
        caption_key="downloads.table.caption",
    )

    try:
        base_url = request.url_for("downloads_table")
    except Exception:  # pragma: no cover - fallback for tests without routing context
        base_url = "/ui/downloads/table"

    def _build_url(offset: int | None) -> str | None:
        if offset is None or offset < 0:
            return None
        query: list[tuple[str, str]] = [("limit", str(page.limit)), ("offset", str(offset))]
        if include_all:
            query.append(("all", "1"))
        if status_filter:
            query.append(("status", status_filter))
        return f"{base_url}?{urlencode(query)}"

    previous_url = _build_url(page.offset - page.limit) if page.has_previous else None
    next_offset = page.offset + page.limit if page.has_next else None
    next_url = _build_url(next_offset) if next_offset is not None else None

    data_attributes = {
        "count": str(len(rows)),
        "limit": str(page.limit),
        "offset": str(page.offset),
    }
    if include_all:
        data_attributes["scope"] = "all"
    if status_filter:
        data_attributes["status"] = status_filter

    pagination = PaginationContext(
        label_key="downloads",
        target="#hx-downloads-table",
        previous_url=previous_url,
        next_url=next_url,
    )

    fragment = TableFragment(
        identifier="hx-downloads-table",
        table=table,
        empty_state_key="downloads",
        data_attributes=data_attributes,
        pagination=pagination if previous_url or next_url else None,
    )

    return {
        "request": request,
        "fragment": fragment,
        "include_all": include_all,
        "active_url": None,
        "all_url": None,
        "refresh_url": None,
    }


def build_jobs_fragment_context(
    request: Request,
    *,
    jobs: Sequence[OrchestratorJob],
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for job in jobs:
        badge = StatusBadge(
            label_key="status.enabled" if job.enabled else "status.disabled",
            variant="success" if job.enabled else "muted",
        )
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=job.name),
                    TableCell(text=job.status),
                    TableCell(badge=badge),
                )
            )
        )

    table = TableDefinition(
        identifier="jobs-table",
        column_keys=("jobs.name", "jobs.status", "jobs.enabled"),
        rows=tuple(rows),
        caption_key="jobs.table.caption",
    )

    fragment = TableFragment(
        identifier="hx-jobs-table",
        table=table,
        empty_state_key="jobs",
        data_attributes={"count": str(len(rows))},
    )

    return {"request": request, "fragment": fragment}


def build_search_results_context(
    request: Request,
    *,
    page: SearchResultsPage,
    query: str,
    sources: Sequence[str],
    csrf_token: str,
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    try:
        action_url = request.url_for("search_download_action")
    except Exception:  # pragma: no cover - fallback for tests
        action_url = "/ui/search/download"
    feedback_target = "#hx-search-feedback"
    for item in page.items:
        score = f"{item.score * 100:.0f}%"
        bitrate = f"{item.bitrate} kbps" if item.bitrate else ""
        if item.download:
            serialised_files = json.dumps(
                [dict(file) for file in item.download.files],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            hidden_fields = {
                "csrftoken": csrf_token,
                "identifier": item.identifier,
                "username": item.download.username,
                "files": serialised_files,
            }
            form = TableCellForm(
                action=action_url,
                method="post",
                submit_label_key="search.action.queue",
                hidden_fields=hidden_fields,
                hx_target=feedback_target,
            )
            action_cell = TableCell(form=form, test_id=f"queue-{item.identifier}")
        else:
            action_cell = TableCell(text_key="search.action.unavailable")
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=item.title),
                    TableCell(text=item.artist or ""),
                    TableCell(text=item.source),
                    TableCell(text=score),
                    TableCell(text=bitrate),
                    action_cell,
                )
            )
        )

    table = TableDefinition(
        identifier="search-results-table",
        column_keys=(
            "search.title",
            "search.artist",
            "search.source",
            "search.score",
            "search.bitrate",
            "search.actions",
        ),
        rows=tuple(rows),
        caption_key="search.results.caption",
    )

    try:
        base_url = request.url_for("search_results")
    except Exception:  # pragma: no cover - fallback for tests
        base_url = "/ui/search/results"

    resolved_sources: tuple[str, ...]
    if sources:
        resolved_sources = tuple(dict.fromkeys(sources))
    else:
        resolved_sources = DEFAULT_SOURCES

    def _make_query(offset: int | None) -> str | None:
        if offset is None or offset < 0:
            return None
        query_params: list[tuple[str, str]] = [
            ("query", query),
            ("limit", str(page.limit)),
            ("offset", str(offset)),
        ]
        for source in resolved_sources:
            query_params.append(("sources", source))
        return f"{base_url}?{urlencode(query_params)}"

    has_previous = page.offset > 0
    previous_offset = page.offset - page.limit if has_previous else None
    next_offset = page.offset + page.limit
    has_next = next_offset < page.total

    pagination = PaginationContext(
        label_key="search",
        target="#hx-search-results",
        previous_url=_make_query(previous_offset) if has_previous else None,
        next_url=_make_query(next_offset) if has_next else None,
    )

    fragment = TableFragment(
        identifier="hx-search-results",
        table=table,
        empty_state_key="search",
        data_attributes={
            "total": str(page.total),
            "limit": str(page.limit),
            "offset": str(page.offset),
            "query": query,
            "sources": ",".join(resolved_sources),
        },
        pagination=pagination if pagination.previous_url or pagination.next_url else None,
    )

    return {"request": request, "fragment": fragment}


def _build_features_table(features: UiFeatures) -> TableDefinition:
    feature_rows = [
        ("feature.spotify", features.spotify, "spotify"),
        ("feature.soulseek", features.soulseek, "soulseek"),
        ("feature.dlq", features.dlq, "dlq"),
        ("feature.imports", features.imports, "imports"),
    ]

    rows = [
        TableRow(
            cells=(
                TableCell(text_key=label_key, test_id=f"feature-{slug}"),
                TableCell(
                    badge=StatusBadge(
                        label_key="status.enabled" if enabled else "status.disabled",
                        variant="success" if enabled else "muted",
                        test_id=f"feature-{slug}-status",
                    )
                ),
            ),
        )
        for label_key, enabled, slug in feature_rows
    ]

    return TableDefinition(
        identifier="features-table",
        column_keys=("dashboard.features.name", "dashboard.features.status"),
        rows=tuple(rows),
        caption_key="dashboard.features.caption",
    )


__all__ = [
    "ActionButton",
    "SuggestedTask",
    "CallToActionCard",
    "ScriptResource",
    "UiAssetConfig",
    "get_ui_assets",
    "AsyncFragment",
    "AlertMessage",
    "CheckboxGroup",
    "CheckboxOption",
    "DefinitionItem",
    "PaginationContext",
    "FormDefinition",
    "FormField",
    "LayoutContext",
    "NavigationContext",
    "NavItem",
    "TableFragment",
    "StatusBadge",
    "TableCell",
    "TableCellForm",
    "TableDefinition",
    "TableRow",
    "ReadinessItem",
    "IntegrationRow",
    "SecretValidationResultView",
    "SecretValidationCard",
    "ServiceHealthView",
    "SpotifyFreeIngestFormContext",
    "SpotifyFreeIngestJobContext",
    "build_spotify_backfill_context",
    "build_spotify_artists_context",
    "build_spotify_page_context",
    "build_spotify_playlists_context",
    "build_spotify_playlist_items_context",
    "build_spotify_track_detail_context",
    "build_spotify_recommendations_context",
    "build_spotify_saved_tracks_context",
    "build_spotify_top_artists_context",
    "build_spotify_top_tracks_context",
    "build_spotify_account_context",
    "build_spotify_status_context",
    "build_spotify_free_ingest_context",
    "build_spotify_free_ingest_form_context",
    "build_spotify_free_ingest_status_context",
    "build_activity_fragment_context",
    "build_activity_page_context",
    "build_admin_page_context",
    "build_settings_page_context",
    "build_settings_form_fragment_context",
    "build_settings_history_fragment_context",
    "build_settings_artist_preferences_fragment_context",
    "build_system_page_context",
    "build_system_liveness_context",
    "build_system_readiness_context",
    "build_system_integrations_context",
    "build_system_service_health_context",
    "build_system_secret_cards",
    "select_system_secret_card",
    "attach_secret_result",
    "build_system_secret_card_context",
    "build_dashboard_page_context",
    "build_downloads_page_context",
    "build_login_page_context",
    "build_operations_page_context",
    "build_primary_navigation",
    "build_soulseek_page_context",
    "build_soulseek_status_context",
    "build_soulseek_config_context",
    "build_soulseek_uploads_context",
    "build_soulseek_downloads_context",
    "build_soulseek_navigation_badge",
    "build_search_page_context",
    "build_downloads_fragment_context",
    "build_jobs_fragment_context",
    "build_search_results_context",
    "build_watchlist_page_context",
    "build_watchlist_fragment_context",
]
