from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from typing import Literal

from fastapi import Request
from starlette.datastructures import URL

from app.config import get_env
from app.ui.session import UiSession

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
    live_updates_mode: Literal["polling", "sse"] = "polling"
    live_updates_source: str | None = None


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
    form: TableCellForm | None = None
    forms: Sequence[TableCellForm] = field(default_factory=tuple)


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
    slug: str
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
class TableCellInput:
    name: str
    input_type: str
    value: str | None = None
    aria_label_key: str | None = None
    min: str | None = None
    max: str | None = None
    step: str | None = None
    test_id: str | None = None
    include_value: bool = False
    include_min: bool = False
    include_max: bool = False
    include_step: bool = False


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
    inputs: Sequence[TableCellInput] = field(default_factory=tuple)


@dataclass(slots=True)
class AsyncFragment:
    identifier: str
    url: str
    target: str
    load_event: str = "load"
    poll_interval_seconds: int | None = None
    swap: str = "outerHTML"
    loading_key: str = "loading"
    event_name: str | None = None

    @property
    def trigger(self) -> str:
        parts = [self.load_event]
        if self.poll_interval_seconds is not None:
            parts.append(f"every {self.poll_interval_seconds}s")
        return ", ".join(parts)


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


def _normalise_status(value: str) -> str:
    return value.strip().lower() if value else ""


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


def _safe_url_for(request: Request, name: str, fallback: str) -> str:
    try:
        resolved = URL(str(request.url_for(name)))
        if resolved.query:
            return f"{resolved.path}?{resolved.query}"
        return resolved.path
    except Exception:  # pragma: no cover - fallback for tests
        return fallback


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


__all__ = [
    "AlertLevel",
    "ButtonMethod",
    "HxMethod",
    "StatusVariant",
    "NavItem",
    "NavigationContext",
    "AlertMessage",
    "MetaTag",
    "ModalDefinition",
    "DefinitionItem",
    "LayoutContext",
    "ScriptResource",
    "UiAssetConfig",
    "FormField",
    "CheckboxOption",
    "CheckboxGroup",
    "FormDefinition",
    "ActionButton",
    "SuggestedTask",
    "CallToActionCard",
    "StatusBadge",
    "TableCell",
    "TableRow",
    "TableDefinition",
    "PaginationContext",
    "TableFragment",
    "TableCellInput",
    "TableCellForm",
    "AsyncFragment",
    "ReadinessItem",
    "IntegrationRow",
    "SecretValidationResultView",
    "SecretValidationCard",
    "ServiceHealthView",
    "get_ui_assets",
    "_build_external_link_cell",
    "_normalize_status",
    "_normalise_status",
    "_status_variant",
    "_system_status_badge",
    "_format_status_text",
    "_format_duration_seconds",
    "_safe_url_for",
    "_build_primary_navigation",
    "build_primary_navigation",
]
