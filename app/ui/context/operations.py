from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

from fastapi import Request

from app.ui.session import UiSession

from .base import (
    AsyncFragment,
    FormDefinition,
    FormField,
    LayoutContext,
    MetaTag,
    PaginationContext,
    StatusBadge,
    TableCell,
    TableDefinition,
    TableFragment,
    TableRow,
    _build_primary_navigation,
    _safe_url_for,
)

if TYPE_CHECKING:
    from app.ui.services import DownloadPage, OrchestratorJob, WatchlistRow


def build_operations_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    use_sse = live_updates_mode == "sse"
    layout = LayoutContext(
        page_id="operations",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
        live_updates_mode=live_updates_mode,
        live_updates_source="/ui/events" if use_sse else None,
    )

    downloads_fragment: AsyncFragment | None = None
    jobs_fragment: AsyncFragment | None = None
    if session.features.dlq:
        downloads_fragment = AsyncFragment(
            identifier="hx-downloads-table",
            url=_safe_url_for(request, "downloads_table", "/ui/downloads/table"),
            target="#hx-downloads-table",
            poll_interval_seconds=None if use_sse else 15,
            loading_key="downloads",
            load_event="revealed",
            event_name="downloads" if use_sse else None,
        )
        jobs_fragment = AsyncFragment(
            identifier="hx-jobs-table",
            url=_safe_url_for(request, "jobs_table", "/ui/jobs/table"),
            target="#hx-jobs-table",
            poll_interval_seconds=None if use_sse else 15,
            loading_key="jobs",
            load_event="revealed",
            event_name="jobs" if use_sse else None,
        )

    watchlist_fragment = AsyncFragment(
        identifier="hx-watchlist-table",
        url=_safe_url_for(request, "watchlist_table", "/ui/watchlist/table"),
        target="#hx-watchlist-table",
        poll_interval_seconds=None if use_sse else 30,
        loading_key="watchlist",
        load_event="revealed",
        event_name="watchlist" if use_sse else None,
    )

    activity_fragment = AsyncFragment(
        identifier="hx-activity-table",
        url=_safe_url_for(request, "activity_table", "/ui/activity/table"),
        target="#hx-activity-table",
        poll_interval_seconds=None if use_sse else 60,
        loading_key="activity",
        load_event="revealed",
        event_name="activity" if use_sse else None,
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
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    use_sse = live_updates_mode == "sse"
    layout = LayoutContext(
        page_id="downloads",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
        live_updates_mode=live_updates_mode,
        live_updates_source="/ui/events" if use_sse else None,
    )

    downloads_fragment = AsyncFragment(
        identifier="hx-downloads-table",
        url=_safe_url_for(request, "downloads_table", "/ui/downloads/table"),
        target="#hx-downloads-table",
        poll_interval_seconds=None if use_sse else 15,
        loading_key="downloads",
        event_name="downloads" if use_sse else None,
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
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    use_sse = live_updates_mode == "sse"
    layout = LayoutContext(
        page_id="jobs",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
        live_updates_mode=live_updates_mode,
        live_updates_source="/ui/events" if use_sse else None,
    )

    jobs_fragment = AsyncFragment(
        identifier="hx-jobs-table",
        url=_safe_url_for(request, "jobs_table", "/ui/jobs/table"),
        target="#hx-jobs-table",
        poll_interval_seconds=None if use_sse else 15,
        loading_key="jobs",
        event_name="jobs" if use_sse else None,
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
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    use_sse = live_updates_mode == "sse"
    layout = LayoutContext(
        page_id="watchlist",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
        live_updates_mode=live_updates_mode,
        live_updates_source="/ui/events" if use_sse else None,
    )

    watchlist_fragment = AsyncFragment(
        identifier="hx-watchlist-table",
        url=_safe_url_for(request, "watchlist_table", "/ui/watchlist/table"),
        target="#hx-watchlist-table",
        poll_interval_seconds=None if use_sse else 30,
        loading_key="watchlist",
        event_name="watchlist" if use_sse else None,
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
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    use_sse = live_updates_mode == "sse"
    layout = LayoutContext(
        page_id="activity",
        role=session.role,
        navigation=_build_primary_navigation(session, active="operations"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
        live_updates_mode=live_updates_mode,
        live_updates_source="/ui/events" if use_sse else None,
    )

    activity_fragment = AsyncFragment(
        identifier="hx-activity-table",
        url=_safe_url_for(request, "activity_table", "/ui/activity/table"),
        target="#hx-activity-table",
        poll_interval_seconds=None if use_sse else 60,
        loading_key="activity",
        event_name="activity" if use_sse else None,
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
    if isinstance(value, (str, int, float)):
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
    except Exception:  # pragma: no cover - fallback for tests
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


def build_watchlist_fragment_context(
    request: Request,
    *,
    entries: Sequence["WatchlistRow"],
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
    page: "DownloadPage",
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


__all__ = [
    "build_operations_page_context",
    "build_downloads_page_context",
    "build_jobs_page_context",
    "build_watchlist_page_context",
    "build_activity_page_context",
    "build_activity_fragment_context",
    "build_watchlist_fragment_context",
    "build_downloads_fragment_context",
    "build_jobs_fragment_context",
]
