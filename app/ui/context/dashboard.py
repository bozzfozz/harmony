from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Request

from app.ui.formatters import format_datetime_display
from app.ui.services.dashboard import (
    DashboardHealthSummary,
    DashboardStatusSummary,
    DashboardWorkerStatus,
)
from app.ui.session import UiFeatures, UiSession

from .base import (
    ActionButton,
    AsyncFragment,
    LayoutContext,
    MetaTag,
    StatusBadge,
    TableCell,
    TableDefinition,
    TableRow,
    _build_primary_navigation,
    _format_duration_seconds,
    _format_status_text,
    _safe_url_for,
    _system_status_badge,
)


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
    "build_dashboard_health_fragment_context",
    "build_dashboard_page_context",
    "build_dashboard_status_fragment_context",
    "build_dashboard_workers_fragment_context",
]
