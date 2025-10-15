from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlencode

import json
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_watchlist_service
from app.errors import AppError
from pydantic import ValidationError
from app.logging import get_logger
from app.logging_events import log_event
from app.ui.context import (
    build_dashboard_page_context,
    build_login_page_context,
)
from app.ui.csrf import attach_csrf_cookie, clear_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.session import (
    UiSession,
    attach_session_cookie,
    clear_session_cookie,
    get_session_manager,
    require_role,
    require_session,
)
from app.utils.activity import activity_manager
from app.schemas.watchlist import WatchlistEntryCreate
from app.services.watchlist_service import WatchlistEntry, WatchlistService

logger = get_logger(__name__)

router = APIRouter(prefix="/ui", tags=["UI"])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _render_alert_fragment(
    request: Request,
    message: str,
    *,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
) -> Response:
    context = {
        "request": request,
        "alerts": (
            {
                "level": "error",
                "text": message or "An unexpected error occurred.",
            },
        ),
    }
    return templates.TemplateResponse(
        request,
        "partials/alerts_fragment.j2",
        context,
        status_code=status_code,
    )

def _format_activity_rows(items: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        details = item.get("details")
        if isinstance(details, Mapping):
            details_text = json.dumps(details, ensure_ascii=False, sort_keys=True)
        elif details is None:
            details_text = ""
        else:
            details_text = str(details)
        rows.append(
            {
                "timestamp": str(item.get("timestamp", "")),
                "type": str(item.get("type", "")),
                "status": str(item.get("status", "")),
                "details": details_text,
            }
        )
    return rows


def _build_activity_pagination(
    request: Request,
    *,
    limit: int,
    offset: int,
    total_count: int,
    type_filter: str | None,
    status_filter: str | None,
) -> dict[str, str | None]:
    prev_offset = offset - limit if offset > 0 else None
    next_offset = offset + limit if offset + limit < total_count else None
    base_url = request.url_for("activity_table")

    filters: list[tuple[str, str]] = []
    if type_filter:
        filters.append(("type", type_filter))
    if status_filter:
        filters.append(("status", status_filter))

    def _url(new_offset: int | None) -> str | None:
        if new_offset is None:
            return None
        query = [("limit", str(limit)), ("offset", str(max(new_offset, 0)))]
        query.extend(filters)
        return f"{base_url}?{urlencode(query)}"

    return {"prev_url": _url(prev_offset), "next_url": _url(next_offset)}


def _format_watchlist_entries(entries: Sequence[WatchlistEntry]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for entry in entries:
        state_key = "watchlist.state.paused" if entry.paused else "watchlist.state.active"
        formatted.append(
            {
                "artist_key": entry.artist_key,
                "priority": entry.priority,
                "state_key": state_key,
            }
        )
    return formatted


def _render_watchlist_table(
    request: Request,
    entries: Sequence[WatchlistEntry],
    *,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    formatted = _format_watchlist_entries(entries)
    context = {
        "request": request,
        "entries": formatted,
        "count": len(formatted),
    }
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
        status_code=status_code,
    )


@router.get("/login", include_in_schema=False)
async def login_form(request: Request) -> Response:
    manager = get_session_manager(request)
    existing_id = request.cookies.get("ui_session")
    if existing_id:
        existing = await manager.get_session(existing_id)
        if existing is not None:
            return RedirectResponse("/ui", status_code=status.HTTP_303_SEE_OTHER)
    context = build_login_page_context(request, error=None)
    return templates.TemplateResponse(request, "pages/login.j2", context)


@router.post("/login", include_in_schema=False)
async def login_action(request: Request) -> Response:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    api_key = values.get("api_key", [""])[0]
    manager = get_session_manager(request)
    try:
        session = await manager.create_session(api_key)
    except HTTPException as exc:
        if exc.status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_503_SERVICE_UNAVAILABLE}:
            message = exc.detail
        else:
            message = "Login failed."
        status_code = (
            exc.status_code
            if exc.status_code != status.HTTP_401_UNAUTHORIZED
            else status.HTTP_400_BAD_REQUEST
        )
        context = build_login_page_context(request, error=message)
        return templates.TemplateResponse(
            request,
            "pages/login.j2",
            context,
            status_code=status_code,
        )

    response = RedirectResponse("/ui", status_code=status.HTTP_303_SEE_OTHER)
    attach_session_cookie(response, session, manager)
    csrf_manager = get_csrf_manager(request)
    attach_csrf_cookie(response, session, csrf_manager)
    log_event(
        logger,
        "ui.session.created",
        component="ui.router",
        status="success",
        role=session.role,
    )
    response.headers.setdefault("HX-Redirect", "/ui")
    return response


@router.get("/", include_in_schema=False)
async def dashboard(
    request: Request,
    session: UiSession = Depends(require_session),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token = csrf_manager.issue(session)
    context = build_dashboard_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/dashboard.j2",
        context,
    )
    attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/logout",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def logout(
    request: Request,
    session: UiSession = Depends(require_session),
) -> Response:
    manager = get_session_manager(request)
    await manager.invalidate(session.identifier)
    response = RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    log_event(
        logger,
        "ui.session.ended",
        component="ui.router",
        status="success",
        role=session.role,
    )
    response.headers.setdefault("HX-Redirect", "/ui/login")
    return response


@router.get("/activity/table", include_in_schema=False)
async def activity_table(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    type_filter: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
    session: UiSession = Depends(require_session),
) -> Response:
    try:
        items, total_count = activity_manager.fetch(
            limit=limit,
            offset=offset,
            type_filter=type_filter,
            status_filter=status_filter,
        )
    except Exception:
        logger.exception("ui.fragment.activity", extra={"limit": limit, "offset": offset})
        log_event(
            logger,
            "ui.fragment.activity",
            component="ui.router",
            status="error",
            role=session.role,
        )
        return _render_alert_fragment(
            request,
            "Unable to load activity entries.",
        )

    rows = _format_activity_rows(items)
    pagination = _build_activity_pagination(
        request,
        limit=limit,
        offset=offset,
        total_count=total_count,
        type_filter=type_filter,
        status_filter=status_filter,
    )
    context = {
        "request": request,
        "rows": rows,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "pagination": pagination,
    }
    log_event(
        logger,
        "ui.fragment.activity",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/activity_table.j2",
        context,
    )


@router.get("/watchlist/table", include_in_schema=False)
async def watchlist_table(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistService = Depends(get_watchlist_service),
) -> Response:
    try:
        entries = service.list_entries()
    except Exception:
        logger.exception("ui.fragment.watchlist")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
        )
        return _render_alert_fragment(
            request,
            "Unable to load watchlist entries.",
        )

    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(entries),
    )
    return _render_watchlist_table(request, entries)


@router.post(
    "/watchlist",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def watchlist_create(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistService = Depends(get_watchlist_service),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    payload_data = {
        "artist_key": values.get("artist_key", [""])[0],
        "priority": values.get("priority", [None])[0],
    }
    try:
        payload = WatchlistEntryCreate.model_validate(payload_data)
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Please provide a valid artist identifier.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        service.create_entry(
            artist_key=payload.artist_key,
            priority=payload.priority,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.watchlist.create")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Failed to add the artist to the watchlist.",
        )

    entries = service.list_entries()
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(entries),
    )
    return _render_watchlist_table(request, entries)
