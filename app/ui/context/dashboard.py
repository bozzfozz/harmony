from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.ui.formatters import format_datetime_display
from app.ui.services.dashboard import (
    DashboardHealthSummary,
    DashboardStatusSummary,
    DashboardWorkerStatus,
)
from app.ui.services.sync import SyncActionResult
from app.ui.session import UiFeatures, UiSession

from .base import (
    ActionButton,
    AsyncFragment,
    LayoutContext,
    MetaTag,
    StatusBadge,
    StatusVariant,
    TableCell,
    TableDefinition,
    TableRow,
    _build_primary_navigation,
    _format_duration_seconds,
    _format_status_text,
    _safe_url_for,
    _system_status_badge,
)
from .common import KpiCard, SidebarSection


@dataclass(slots=True)
class DashboardConnectionView:
    name: str
    badge: StatusBadge


@dataclass(slots=True)
class DashboardIssueView:
    component: str
    message: str


@dataclass(slots=True)
class DashboardStatusView:
    badge: StatusBadge
    status_text: str
    version: str | None
    uptime_text: str | None
    readiness_badge: StatusBadge | None
    readiness_text: str | None
    issues: Sequence[DashboardIssueView]
    connections: Sequence[DashboardConnectionView]


@dataclass(slots=True)
class DashboardHealthView:
    liveness_badge: StatusBadge
    liveness_text: str
    readiness_badge: StatusBadge
    readiness_text: str
    issues: Sequence[DashboardIssueView]


@dataclass(slots=True)
class DashboardWorkerView:
    name: str
    badge: StatusBadge
    status_text: str
    queue_size: str | None
    last_seen: str | None
    meta: str | None


@dataclass(slots=True)
class DashboardActionMetric:
    label: str
    value: str
    test_id: str | None = None


@dataclass(slots=True)
class DashboardActionResultView:
    label: str
    badge: StatusBadge
    test_id: str | None = None


@dataclass(slots=True)
class DashboardActionState:
    status_badge: StatusBadge
    message: str
    timestamp: str | None
    results: Sequence[DashboardActionResultView]
    metrics: Sequence[DashboardActionMetric]
    errors: Sequence[str]
    has_data: bool = False


def build_dashboard_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    actions: list[ActionButton] = []
    sync_state = build_dashboard_action_state_idle()

    if session.allows("operator") and session.features.spotify:
        sync_url = _safe_url_for(
            request,
            "dashboard_sync_action",
            "/ui/dashboard/sync",
        )
        actions.append(
            ActionButton(
                identifier="dashboard-sync-action",
                label_key="dashboard.action.sync",
                url=sync_url,
                method="post",
                confirm_text="Trigger a manual sync run now?",
                target="#ui-alert-region",
                success_swap="innerHTML",
                error_swap="innerHTML",
            )
        )

    layout = LayoutContext(
        page_id="dashboard",
        role=session.role,
        navigation=_build_primary_navigation(session, active="home"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    features_table = _build_features_table(session.features)

    status_url = _safe_url_for(
        request,
        "dashboard_status_fragment",
        "/ui/dashboard/status",
    )
    health_url = _safe_url_for(
        request,
        "dashboard_health_fragment",
        "/ui/dashboard/health",
    )
    workers_url = _safe_url_for(
        request,
        "dashboard_workers_fragment",
        "/ui/dashboard/workers",
    )

    try:
        activity_url = request.url_for("activity_table")
    except Exception:  # pragma: no cover - fallback for tests
        activity_url = "/ui/activity/table"

    status_fragment = AsyncFragment(
        identifier="hx-dashboard-status",
        url=status_url,
        target="#hx-dashboard-status",
        poll_interval_seconds=30,
        swap="innerHTML",
    )
    health_fragment = AsyncFragment(
        identifier="hx-dashboard-health",
        url=health_url,
        target="#hx-dashboard-health",
        poll_interval_seconds=60,
        swap="innerHTML",
    )
    workers_fragment = AsyncFragment(
        identifier="hx-dashboard-workers",
        url=workers_url,
        target="#hx-dashboard-workers",
        poll_interval_seconds=45,
        swap="innerHTML",
    )
    activity_fragment = AsyncFragment(
        identifier="hx-activity-table",
        url=activity_url,
        target="#hx-activity-table",
        poll_interval_seconds=60,
    )

    kpi_cards = _build_dashboard_kpi_cards(session)
    sidebar_sections = _build_dashboard_sidebar_sections(session)

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "features_table": features_table,
        "actions": tuple(actions),
        "csrf_token": csrf_token,
        "status_fragment": status_fragment,
        "health_fragment": health_fragment,
        "workers_fragment": workers_fragment,
        "activity_fragment": activity_fragment,
        "sync_state": sync_state,
        "kpi_cards": kpi_cards,
        "sidebar_sections": sidebar_sections,
    }


def build_dashboard_status_fragment_context(
    request: Request,
    *,
    summary: DashboardStatusSummary,
) -> Mapping[str, Any]:
    badge = _system_status_badge(
        summary.status,
        test_id="dashboard-status-badge",
    )
    readiness_badge = (
        _system_status_badge(summary.readiness_status, test_id="dashboard-readiness-badge")
        if summary.readiness_status is not None
        else None
    )
    readiness_text = (
        _format_status_text(summary.readiness_status)
        if summary.readiness_status is not None
        else None
    )

    connections = tuple(
        DashboardConnectionView(
            name=connection.name,
            badge=_system_status_badge(
                connection.status,
                test_id=f"dashboard-connection-{_slugify(connection.name)}",
            ),
        )
        for connection in summary.connections
    )

    issues = tuple(
        DashboardIssueView(component=issue.component, message=issue.message)
        for issue in summary.readiness_issues
    )

    uptime_text = _format_duration_seconds(summary.uptime_seconds)
    status_view = DashboardStatusView(
        badge=badge,
        status_text=_format_status_text(summary.status),
        version=summary.version,
        uptime_text=uptime_text,
        readiness_badge=readiness_badge,
        readiness_text=readiness_text,
        issues=issues,
        connections=connections,
    )

    return {
        "request": request,
        "summary": status_view,
    }


def build_dashboard_health_fragment_context(
    request: Request,
    *,
    summary: DashboardHealthSummary,
) -> Mapping[str, Any]:
    liveness_badge = _system_status_badge(
        summary.live_status,
        test_id="dashboard-health-live",
    )
    readiness_badge = _system_status_badge(
        summary.ready_status,
        test_id="dashboard-health-ready",
    )
    issues = tuple(
        DashboardIssueView(component=issue.component, message=issue.message)
        for issue in summary.issues
    )

    health_view = DashboardHealthView(
        liveness_badge=liveness_badge,
        liveness_text=_format_status_text(summary.live_status),
        readiness_badge=readiness_badge,
        readiness_text=_format_status_text(summary.ready_status),
        issues=issues,
    )
    return {
        "request": request,
        "health": health_view,
    }


def build_dashboard_workers_fragment_context(
    request: Request,
    *,
    workers: Sequence[DashboardWorkerStatus],
) -> Mapping[str, Any]:
    worker_views: list[DashboardWorkerView] = []
    for worker in workers:
        badge = _system_status_badge(
            worker.status,
            test_id=f"dashboard-worker-{_slugify(worker.name)}",
        )
        queue_text = str(worker.queue_size) if worker.queue_size is not None else None
        last_seen = _format_last_seen(worker.last_seen)
        meta: str | None = None
        if worker.component:
            meta = f"Component: {worker.component}"
        elif worker.job:
            meta = f"Job: {worker.job}"
        worker_views.append(
            DashboardWorkerView(
                name=worker.name,
                badge=badge,
                status_text=_format_status_text(worker.status),
                queue_size=queue_text,
                last_seen=last_seen,
                meta=meta,
            )
        )

    return {
        "request": request,
        "workers": tuple(worker_views),
    }


def build_dashboard_action_state_idle() -> DashboardActionState:
    """Return the placeholder state for the dashboard action panel."""

    badge = StatusBadge(
        label_key="dashboard.sync.status.idle",
        variant="muted",
        test_id="dashboard-sync-status",
    )
    return DashboardActionState(
        status_badge=badge,
        message="Manual sync has not been triggered yet.",
        timestamp=None,
        results=(),
        metrics=(),
        errors=(),
        has_data=False,
    )


def build_dashboard_action_state_from_sync(
    result: SyncActionResult,
) -> DashboardActionState:
    """Build a rendered view model from a sync trigger payload."""

    timestamp = format_datetime_display(datetime.now(tz=UTC))
    results = _build_sync_results(result.results)
    metrics = _build_sync_metrics(result.counters)
    errors = _build_sync_errors(result.errors)
    summary = _compose_sync_summary(result.message, len(results), len(errors))
    badge = _overall_sync_badge(len(results), len(errors))
    return DashboardActionState(
        status_badge=badge,
        message=summary,
        timestamp=timestamp,
        results=tuple(results),
        metrics=tuple(metrics),
        errors=tuple(errors),
        has_data=True,
    )


def build_dashboard_action_state_from_error(
    message: str,
    *,
    meta: Mapping[str, Any] | None = None,
) -> DashboardActionState:
    """Create a sync panel state describing an error condition."""

    timestamp = format_datetime_display(datetime.now(tz=UTC))
    errors = _format_sync_error_meta(meta)
    if not errors:
        errors = [message]
    badge = StatusBadge(
        label_key="dashboard.sync.status.failed",
        variant="danger",
        test_id="dashboard-sync-status",
    )
    return DashboardActionState(
        status_badge=badge,
        message=message,
        timestamp=timestamp,
        results=(),
        metrics=(),
        errors=tuple(errors),
        has_data=True,
    )


_SYNC_SOURCE_LABELS: Mapping[str, str] = {
    "playlists": "Playlists",
    "library_scan": "Library scan",
    "auto_sync": "Auto sync",
}

_SYNC_METRIC_LABELS: Mapping[str, str] = {
    "tracks_synced": "Tracks synced",
    "tracks_skipped": "Tracks skipped",
    "errors": "Reported errors",
}

_SYNC_RESULT_BADGES: Mapping[str, tuple[str, StatusVariant]] = {
    "completed": ("dashboard.sync.result.completed", "success"),
    "success": ("dashboard.sync.result.completed", "success"),
    "running": ("dashboard.sync.result.running", "muted"),
    "queued": ("dashboard.sync.result.queued", "muted"),
    "pending": ("dashboard.sync.result.queued", "muted"),
    "failed": ("dashboard.sync.result.failed", "danger"),
    "error": ("dashboard.sync.result.failed", "danger"),
}


def _build_sync_results(results: Mapping[str, str]) -> list[DashboardActionResultView]:
    items: list[DashboardActionResultView] = []
    for name, status_text in sorted(results.items()):
        slug = _slugify(str(name))
        test_id = f"dashboard-sync-result-{slug}"
        badge = _sync_result_badge(status_text, test_id=test_id)
        label = _format_sync_source_label(name)
        items.append(
            DashboardActionResultView(
                label=label,
                badge=badge,
                test_id=test_id,
            )
        )
    return items


def _build_sync_metrics(counters: Mapping[str, int]) -> list[DashboardActionMetric]:
    metrics: list[DashboardActionMetric] = []
    for key, value in sorted(counters.items()):
        slug = _slugify(str(key))
        metrics.append(
            DashboardActionMetric(
                label=_format_sync_metric_label(key),
                value=str(value),
                test_id=f"dashboard-sync-metric-{slug}",
            )
        )
    return metrics


def _build_sync_errors(errors: Mapping[str, str]) -> list[str]:
    messages: list[str] = []
    for name, detail in sorted(errors.items()):
        label = _format_sync_source_label(name)
        text = detail.strip() if isinstance(detail, str) else str(detail or "")
        messages.append(f"{label}: {text}" if text else label)
    return messages


def _format_sync_source_label(name: Any) -> str:
    normalized = str(name or "").strip().lower()
    if normalized in _SYNC_SOURCE_LABELS:
        return _SYNC_SOURCE_LABELS[normalized]
    fallback = normalized.replace("_", " ").strip()
    return fallback.title() if fallback else "Source"


def _format_sync_metric_label(name: Any) -> str:
    normalized = str(name or "").strip().lower()
    return _SYNC_METRIC_LABELS.get(normalized, normalized.replace("_", " ").title() or "Value")


def _sync_result_badge(status: str, *, test_id: str) -> StatusBadge:
    normalized = (status or "").strip().lower()
    label_key, variant = _SYNC_RESULT_BADGES.get(
        normalized,
        ("dashboard.sync.result.unknown", "muted"),
    )
    return StatusBadge(label_key=label_key, variant=variant, test_id=test_id)


def _overall_sync_badge(results_count: int, error_count: int) -> StatusBadge:
    if results_count and error_count:
        label_key = "dashboard.sync.status.partial"
        variant: StatusVariant = "muted"
    elif results_count:
        label_key = "dashboard.sync.status.success"
        variant = "success"
    elif error_count:
        label_key = "dashboard.sync.status.failed"
        variant = "danger"
    else:
        label_key = "dashboard.sync.status.idle"
        variant = "muted"
    return StatusBadge(label_key=label_key, variant=variant, test_id="dashboard-sync-status")


def _compose_sync_summary(message: str, results_count: int, error_count: int) -> str:
    base = (message or "Manual sync triggered").strip()
    details: list[str] = []
    if results_count:
        details.append(_pluralize(results_count, "source updated", "sources updated"))
    if error_count:
        details.append(_pluralize(error_count, "warning"))
    if not details:
        return base
    normalized_base = base.rstrip(". ")
    return f"{normalized_base} — {', '.join(details)}."


def _pluralize(count: int, singular: str, plural: str | None = None) -> str:
    term = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {term}"


def _format_sync_error_meta(meta: Mapping[str, Any] | None) -> list[str]:
    if not meta:
        return []
    missing = meta.get("missing")
    if not isinstance(missing, Mapping):
        return []
    messages: list[str] = []
    for service, details in sorted(missing.items()):
        label = _format_sync_source_label(service)
        detail_text = _join_meta_details(details)
        if detail_text:
            messages.append(f"{label}: missing {detail_text}")
        else:
            messages.append(f"{label}: missing credentials")
    return messages


def _join_meta_details(details: Any) -> str:
    if isinstance(details, str):
        return details.strip()
    if isinstance(details, Sequence) and not isinstance(details, str | bytes):
        parts = [str(item).strip() for item in details if str(item).strip()]
        return ", ".join(sorted(parts))
    return ""


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


def _build_dashboard_kpi_cards(session: UiSession) -> tuple[KpiCard, ...]:
    """Return KPI card view models for the dashboard layout."""

    # No aggregated dashboard metrics are available yet. Return an empty tuple to
    # keep the layout contract stable for future extensions.
    return ()


def _build_dashboard_sidebar_sections(session: UiSession) -> tuple[SidebarSection, ...]:
    """Return sidebar sections for the dashboard layout.

    The dashboard currently renders bespoke action controls. Providing an empty
    tuple ensures the template can conditionally mount shared sidebar sections
    without adding placeholder markup.
    """

    return ()


def _format_last_seen(last_seen: str | None) -> str | None:
    if not last_seen:
        return None
    try:
        parsed = datetime.fromisoformat(last_seen)
    except ValueError:
        return last_seen
    formatted = format_datetime_display(parsed)
    return formatted or parsed.isoformat()


def _slugify(value: str) -> str:
    slug = ["-" if not char.isalnum() else char.lower() for char in value]
    collapsed = "".join(slug).strip("-")
    return collapsed or "item"


__all__ = [
    "DashboardConnectionView",
    "DashboardHealthView",
    "DashboardIssueView",
    "DashboardStatusView",
    "DashboardWorkerView",
    "DashboardActionMetric",
    "DashboardActionResultView",
    "DashboardActionState",
    "build_dashboard_health_fragment_context",
    "build_dashboard_page_context",
    "build_dashboard_status_fragment_context",
    "build_dashboard_workers_fragment_context",
    "build_dashboard_action_state_idle",
    "build_dashboard_action_state_from_sync",
    "build_dashboard_action_state_from_error",
]
