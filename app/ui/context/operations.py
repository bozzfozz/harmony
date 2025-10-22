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
    PaginationContext,
    StatusBadge,
    TableCell,
    TableCellForm,
    TableCellInput,
    TableDefinition,
    TableFragment,
    TableRow,
    _safe_url_for,
)
from .common import KpiCard
from .operations_layout import (
    build_downloads_async_fragment,
    build_jobs_async_fragment,
    build_operations_layout,
    build_operations_sidebar_sections,
)

_LIVE_UPDATES_STREAMING_VALUE = "Streaming"
_LIVE_UPDATES_POLLING_VALUE = "Polling"
_LIVE_UPDATES_STREAMING_BADGE = "Real-time"
_LIVE_UPDATES_POLLING_BADGE = "Interval"
_LIVE_UPDATES_STREAMING_DESCRIPTION = "Server-sent events keep this overview in sync in real time."
_LIVE_UPDATES_POLLING_DESCRIPTION = "HTMX polling refreshes the overview on a schedule."
_OPERATIONS_LIVE_UPDATES_TITLE = "Live updates"

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
    layout = build_operations_layout(
        session,
        page_id="operations",
        csrf_token=csrf_token,
        live_updates_mode=live_updates_mode,
    )

    downloads_fragment: AsyncFragment | None = None
    jobs_fragment: AsyncFragment | None = None
    if session.features.dlq:
        downloads_fragment = build_downloads_async_fragment(
            request,
            use_sse=use_sse,
            load_event="revealed",
        )
        jobs_fragment = build_jobs_async_fragment(
            request,
            use_sse=use_sse,
            load_event="revealed",
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

    kpi_cards = _build_operations_kpi_cards(live_updates_mode)
    dashboard_url = "/ui"
    downloads_page_url = (
        _safe_url_for(request, "downloads_page", "/ui/downloads") if session.features.dlq else None
    )
    jobs_page_url = (
        _safe_url_for(request, "jobs_page", "/ui/jobs") if session.features.dlq else None
    )
    watchlist_page_url = _safe_url_for(request, "watchlist_page", "/ui/watchlist")
    activity_page_url = _safe_url_for(request, "activity_page", "/ui/activity")
    sidebar_sections = build_operations_sidebar_sections(
        live_updates_mode=live_updates_mode,
        downloads_url=downloads_page_url,
        jobs_url=jobs_page_url,
        watchlist_url=watchlist_page_url,
        activity_url=activity_page_url,
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
        "dashboard_url": dashboard_url,
        "downloads_page_url": downloads_page_url or "/ui/downloads",
        "jobs_page_url": jobs_page_url or "/ui/jobs",
        "watchlist_page_url": watchlist_page_url,
        "activity_page_url": activity_page_url,
        "kpi_cards": kpi_cards,
        "sidebar_sections": sidebar_sections,
    }


def build_watchlist_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    use_sse = live_updates_mode == "sse"
    layout = build_operations_layout(
        session,
        page_id="watchlist",
        csrf_token=csrf_token,
        live_updates_mode=live_updates_mode,
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
    layout = build_operations_layout(
        session,
        page_id="activity",
        csrf_token=csrf_token,
        live_updates_mode=live_updates_mode,
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


def _build_operations_kpi_cards(
    live_updates_mode: Literal["polling", "sse"],
) -> tuple[KpiCard, ...]:
    """Return KPI cards summarising operations overview state."""

    if live_updates_mode == "sse":
        value = _LIVE_UPDATES_STREAMING_VALUE
        description = _LIVE_UPDATES_STREAMING_DESCRIPTION
        badge_label = _LIVE_UPDATES_STREAMING_BADGE
        badge_variant = "success"
    else:
        value = _LIVE_UPDATES_POLLING_VALUE
        description = _LIVE_UPDATES_POLLING_DESCRIPTION
        badge_label = _LIVE_UPDATES_POLLING_BADGE
        badge_variant = "muted"

    card = KpiCard(
        identifier="operations-live-updates",
        title=_OPERATIONS_LIVE_UPDATES_TITLE,
        value=value,
        description=description,
        badge_label=badge_label,
        badge_variant=badge_variant,
        test_id="operations-live-updates-kpi",
    )
    return (card,)


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


__all__ = [
    "build_operations_page_context",
    "build_watchlist_page_context",
    "build_activity_page_context",
    "build_activity_fragment_context",
    "build_watchlist_fragment_context",
]
