from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

from fastapi import Request

from app.ui.session import UiSession

from .base import (
    PaginationContext,
    TableCell,
    TableCellForm,
    TableCellInput,
    TableDefinition,
    TableFragment,
    TableRow,
    _safe_url_for,
)
from .operations_layout import (
    build_downloads_async_fragment,
    build_operations_layout,
    build_operations_sidebar_sections,
)

if TYPE_CHECKING:
    from app.ui.services import DownloadPage


def build_downloads_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    live_updates_mode: Literal["polling", "sse"] = "polling",
) -> Mapping[str, Any]:
    """Build the template context for the downloads management page."""

    use_sse = live_updates_mode == "sse"
    layout = build_operations_layout(
        session,
        page_id="downloads",
        csrf_token=csrf_token,
        live_updates_mode=live_updates_mode,
    )

    downloads_fragment = build_downloads_async_fragment(
        request,
        use_sse=use_sse,
    )

    operations_url = _safe_url_for(request, "operations_page", "/ui/operations")
    downloads_url = _safe_url_for(request, "downloads_page", "/ui/downloads")
    jobs_url = _safe_url_for(request, "jobs_page", "/ui/jobs") if session.features.dlq else None
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
        "downloads_fragment": downloads_fragment,
        "operations_url": operations_url,
        "sidebar_sections": sidebar_sections,
    }


def build_downloads_fragment_context(
    request: Request,
    *,
    page: DownloadPage,
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
                    TableCell(text=str(entry.identifier)),
                    TableCell(text=entry.filename or ""),
                    TableCell(text=entry.status or ""),
                    TableCell(text=progress),
                    TableCell(form=priority_form),
                    TableCell(text=entry.username or ""),
                    TableCell(text=updated_at),
                    TableCell(forms=(retry_form, cancel_form)),
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


__all__ = [
    "build_downloads_page_context",
    "build_downloads_fragment_context",
]
