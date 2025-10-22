from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from fastapi import Request

from app.ui.session import UiSession

from .base import StatusBadge, TableCell, TableDefinition, TableFragment, TableRow, _safe_url_for
from .operations_layout import (
    build_jobs_async_fragment,
    build_operations_layout,
    build_operations_sidebar_sections,
)


def build_jobs_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    """Build the template context for the orchestrator jobs page."""

    use_sse = live_updates_mode == "sse"
    layout = build_operations_layout(
        session,
        page_id="jobs",
        csrf_token=csrf_token,
        live_updates_mode=live_updates_mode,
    )

    jobs_fragment = build_jobs_async_fragment(
        request,
        use_sse=use_sse,
    )

    operations_url = _safe_url_for(request, "operations_page", "/ui/operations")
    downloads_url = (
        _safe_url_for(request, "downloads_page", "/ui/downloads") if session.features.dlq else None
    )
    jobs_url = _safe_url_for(request, "jobs_page", "/ui/jobs")
    watchlist_url = _safe_url_for(request, "watchlist_page", "/ui/watchlist")
    activity_url = _safe_url_for(request, "activity_page", "/ui/activity")

    sidebar_sections = build_operations_sidebar_sections(
        live_updates_mode=live_updates_mode,
        downloads_url=downloads_url,
        jobs_url=jobs_url,
        watchlist_url=watchlist_url,
        activity_url=activity_url,
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "jobs_fragment": jobs_fragment,
        "operations_url": operations_url,
        "sidebar_sections": sidebar_sections,
    }


def build_jobs_fragment_context(
    request: Request,
    *,
    jobs: Sequence["OrchestratorJob"],
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
                ),
                test_id=f"job-row-{job.name}",
            )
        )

    table = TableDefinition(
        identifier="jobs-table",
        column_keys=(
            "jobs.name",
            "jobs.status",
            "jobs.enabled",
        ),
        rows=tuple(rows),
        caption_key="jobs.table.caption",
    )

    fragment = TableFragment(
        identifier="hx-jobs-table",
        table=table,
        empty_state_key="jobs",
    )

    return {"request": request, "fragment": fragment}


__all__ = [
    "build_jobs_page_context",
    "build_jobs_fragment_context",
]
