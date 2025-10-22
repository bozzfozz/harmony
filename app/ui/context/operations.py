from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
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
    TableCellForm,
    TableCellInput,
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


def _normalize_artist_key_for_id(value: str) -> str:
    candidate = value.lower()
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate)
    candidate = candidate.strip("-")
    return candidate or "entry"


def _normalise_paging_param(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate or None


def _build_watchlist_hidden_fields(
    csrf_token: str,
    limit: str | None,
    offset: str | None,
) -> dict[str, str]:
    fields: dict[str, str] = {"csrftoken": csrf_token}
    if limit is not None:
        fields["limit"] = limit
    if offset is not None:
        fields["offset"] = offset
    return fields


def _build_watchlist_row(
    entry: "WatchlistRow",
    hidden_fields: Mapping[str, str],
) -> TableRow:
    slug = _normalize_artist_key_for_id(entry.artist_key)
    priority_input = TableCellInput(
        name="priority",
        input_type="number",
        value=str(entry.priority),
        aria_label_key="watchlist.priority.input",
        min="0",
        test_id=f"watchlist-priority-input-{slug}",
        include_value=True,
        include_min=True,
    )
    priority_form = TableCellForm(
        action=f"/ui/watchlist/{entry.artist_key}/priority",
        method="post",
        submit_label_key="watchlist.priority.update",
        hidden_fields=dict(hidden_fields),
        hx_target="#hx-watchlist-table",
        hx_swap="outerHTML",
        test_id=f"watchlist-priority-submit-{slug}",
        inputs=(priority_input,),
    )

    action_forms: list[TableCellForm] = []
    if entry.paused:
        action_forms.append(
            TableCellForm(
                action=f"/ui/watchlist/{entry.artist_key}/resume",
                method="post",
                submit_label_key="watchlist.resume",
                hidden_fields=dict(hidden_fields),
                hx_target="#hx-watchlist-table",
                hx_swap="outerHTML",
                test_id=f"watchlist-resume-{slug}",
            )
        )
    else:
        action_forms.append(
            TableCellForm(
                action=f"/ui/watchlist/{entry.artist_key}/pause",
                method="post",
                submit_label_key="watchlist.pause",
                hidden_fields=dict(hidden_fields),
                hx_target="#hx-watchlist-table",
                hx_swap="outerHTML",
                test_id=f"watchlist-pause-{slug}",
            )
        )

    action_forms.append(
        TableCellForm(
            action=f"/ui/watchlist/{entry.artist_key}/delete",
            method="post",
            submit_label_key="watchlist.delete",
            hidden_fields=dict(hidden_fields),
            hx_target="#hx-watchlist-table",
            hx_swap="outerHTML",
            test_id=f"watchlist-delete-{slug}",
        )
    )

    return TableRow(
        test_id=f"watchlist-row-{slug}",
        cells=(
            TableCell(text=entry.artist_key, test_id=f"watchlist-artist-{slug}"),
            TableCell(form=priority_form, test_id=f"watchlist-priority-{slug}"),
            TableCell(text_key=entry.state_key, test_id=f"watchlist-state-{slug}"),
            TableCell(forms=tuple(action_forms), test_id=f"watchlist-actions-{slug}"),
        ),
    )


def build_watchlist_fragment_context(
    request: Request,
    *,
    entries: Sequence["WatchlistRow"],
    csrf_token: str,
    limit: str | None = None,
    offset: str | None = None,
) -> Mapping[str, Any]:
    limit_value = _normalise_paging_param(limit)
    offset_value = _normalise_paging_param(offset)
    hidden_fields = _build_watchlist_hidden_fields(csrf_token, limit_value, offset_value)

    rows = tuple(_build_watchlist_row(entry, hidden_fields) for entry in entries)

    table = TableDefinition(
        identifier="watchlist-table",
        column_keys=(
            "watchlist.artist",
            "watchlist.priority",
            "watchlist.state",
            "watchlist.actions",
        ),
        rows=tuple(rows),
        caption_key="watchlist.table.caption",
    )

    fragment = TableFragment(
        identifier="hx-watchlist-table",
        table=table,
        empty_state_key="watchlist",
        data_attributes={
            key: value
            for key, value in (
                ("count", str(len(rows))),
                ("limit", limit_value),
                ("offset", offset_value),
            )
            if value is not None
        },
    )

    return {"request": request, "fragment": fragment}


def build_downloads_fragment_context(
    request: Request,
    *,
    page: "DownloadPage",
    csrf_token: str,
    status_filter: str | None = None,
    include_all: bool = False,
) -> Mapping[str, Any]:
    scope_value = "all" if include_all else "active"
    target = "#hx-downloads-table"
    swap = "outerHTML"

    def _normalise_status(value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None

    status_value = _normalise_status(status_filter)

    hidden_fields: dict[str, str] = {
        "csrftoken": csrf_token,
        "scope": scope_value,
        "limit": str(page.limit),
        "offset": str(page.offset),
    }
    if status_value:
        hidden_fields["status"] = status_value

    retryable_states = {"failed", "dead_letter", "cancelled"}
    cancellable_states = {"queued", "running", "downloading"}

    rows: list[TableRow] = []
    for entry in page.items:
        progress = ""
        if entry.progress is not None:
            progress = f"{entry.progress * 100:.0f}%"
        updated_at = entry.updated_at.isoformat() if entry.updated_at else ""

        try:
            priority_url = request.url_for(
                "downloads_priority_update", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests without routing context
            priority_url = f"/ui/downloads/{entry.identifier}/priority"

        try:
            retry_url = request.url_for("downloads_retry", download_id=str(entry.identifier))
        except Exception:  # pragma: no cover - fallback for tests without routing context
            retry_url = f"/ui/downloads/{entry.identifier}/retry"

        try:
            cancel_url = request.url_for("downloads_cancel", download_id=str(entry.identifier))
        except Exception:  # pragma: no cover - fallback for tests without routing context
            cancel_url = f"/ui/downloads/{entry.identifier}"

        normalized_status = (entry.status or "").strip().lower()
        can_retry = normalized_status in retryable_states
        can_cancel = normalized_status in cancellable_states

        priority_input = TableCellInput(
            name="priority",
            input_type="number",
            value=str(entry.priority),
            aria_label_key="downloads.priority.input",
            min="0",
            test_id=f"download-priority-input-{entry.identifier}",
            include_value=True,
            include_min=True,
        )

        priority_form = TableCellForm(
            action=priority_url,
            method="post",
            submit_label_key="downloads.priority.update",
            hidden_fields=dict(hidden_fields),
            hx_target=target,
            hx_swap=swap,
            test_id=f"download-priority-submit-{entry.identifier}",
            inputs=(priority_input,),
        )

        retry_form = TableCellForm(
            action=retry_url,
            method="post",
            submit_label_key="downloads.retry",
            hidden_fields=dict(hidden_fields),
            hx_target=target,
            hx_swap=swap,
            disabled=not can_retry,
            test_id=f"download-retry-{entry.identifier}",
        )

        cancel_form = TableCellForm(
            action=cancel_url,
            method="post",
            submit_label_key="downloads.cancel",
            hidden_fields=dict(hidden_fields),
            hx_target=target,
            hx_swap=swap,
            hx_method="delete",
            disabled=not can_cancel,
            test_id=f"download-cancel-{entry.identifier}",
        )

        rows.append(
            TableRow(
                test_id=f"download-row-{entry.identifier}",
                cells=(
                    TableCell(
                        text=str(entry.identifier), test_id=f"download-id-{entry.identifier}"
                    ),
                    TableCell(text=entry.filename, test_id=f"download-filename-{entry.identifier}"),
                    TableCell(text=entry.status, test_id=f"download-status-{entry.identifier}"),
                    TableCell(text=progress, test_id=f"download-progress-{entry.identifier}"),
                    TableCell(form=priority_form, test_id=f"download-priority-{entry.identifier}"),
                    TableCell(
                        text=entry.username or "", test_id=f"download-user-{entry.identifier}"
                    ),
                    TableCell(text=updated_at, test_id=f"download-updated-{entry.identifier}"),
                    TableCell(
                        forms=(retry_form, cancel_form),
                        test_id=f"download-actions-{entry.identifier}",
                    ),
                ),
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
            "downloads.actions",
        ),
        rows=tuple(rows),
        caption_key="downloads.table.caption",
    )

    try:
        base_url = request.url_for("downloads_table")
    except Exception:  # pragma: no cover - fallback for tests without routing context
        base_url = "/ui/downloads/table"

    def _scope_url(*, all_scope: bool, offset_value: int | None = None) -> str:
        offset_candidate = page.offset if offset_value is None else max(offset_value, 0)
        query: list[tuple[str, str]] = [
            ("limit", str(page.limit)),
            ("offset", str(offset_candidate)),
        ]
        if all_scope:
            query.append(("all", "1"))
        if status_value:
            query.append(("status", status_value))
        return f"{base_url}?{urlencode(query)}"

    previous_url = None
    if page.has_previous:
        previous_url = _scope_url(all_scope=include_all, offset_value=page.offset - page.limit)

    next_url = None
    if page.has_next:
        next_url = _scope_url(all_scope=include_all, offset_value=page.offset + page.limit)

    pagination = (
        PaginationContext(
            label_key="downloads",
            target=target,
            swap=swap,
            previous_url=previous_url,
            next_url=next_url,
        )
        if previous_url or next_url
        else None
    )

    refresh_url = _scope_url(all_scope=include_all)
    active_url = _scope_url(all_scope=False)
    all_url = _scope_url(all_scope=True)

    export_url = _safe_url_for(
        request,
        "downloads_export",
        "/ui/downloads/export",
    )

    data_attributes = {
        "count": str(len(rows)),
        "limit": str(page.limit),
        "offset": str(page.offset),
        "scope": scope_value,
        "action-target": target,
        "action-swap": swap,
        "refresh-url": refresh_url,
    }
    if status_value:
        data_attributes["status"] = status_value
    data_attributes["export-url"] = export_url

    fragment = TableFragment(
        identifier="hx-downloads-table",
        table=table,
        empty_state_key="downloads",
        data_attributes=data_attributes,
        pagination=pagination,
    )

    return {
        "request": request,
        "fragment": fragment,
        "csrf_token": csrf_token,
        "include_all": include_all,
        "status_filter": status_value,
        "active_url": active_url,
        "all_url": all_url,
        "refresh_url": refresh_url,
        "cleanup_url": None,
        "cleanup_target": target,
        "cleanup_swap": swap,
        "cleanup_disabled": True,
        "export_url": export_url,
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
