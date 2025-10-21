from __future__ import annotations

import json
from typing import Sequence
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError

from app.api.search import DEFAULT_SOURCES
from app.dependencies import get_download_service
from app.errors import AppError
from app.logging_events import log_event
from app.schemas import SoulseekDownloadRequest
from app.services.download_service import DownloadService
from app.ui.context.base import AlertMessage
from app.ui.context.search import (
    build_search_page_context,
    build_search_results_context,
)
from app.ui.csrf import attach_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _render_alert_fragment,
    logger,
    templates,
)
from app.ui.services import SearchUiService, get_search_ui_service
from app.ui.session import UiSession, require_role

router = APIRouter()


async def _render_search_results_fragment(
    request: Request,
    session: UiSession,
    service: SearchUiService,
    *,
    raw_query: str | None,
    raw_limit: str | int | None,
    raw_offset: str | int | None,
    raw_sources: Sequence[str] | None,
) -> Response:
    if not session.features.soulseek:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    query = (raw_query or "").strip()
    if not query:
        return _render_alert_fragment(
            request,
            "Please provide a search query.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    def _coerce_int(
        value: str | int | None, default: int, *, minimum: int, maximum: int | None = None
    ) -> int:
        try:
            coerced = int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            coerced = default
        if maximum is None:
            return max(minimum, coerced)
        return max(minimum, min(coerced, maximum))

    limit_value = _coerce_int(raw_limit, 25, minimum=1, maximum=100)
    offset_value = _coerce_int(raw_offset, 0, minimum=0)

    cleaned_sources: list[str] = []
    for entry in raw_sources or ():
        normalised = str(entry).strip().lower()
        if normalised and normalised not in cleaned_sources:
            cleaned_sources.append(normalised)
    resolved_sources: tuple[str, ...] = tuple(cleaned_sources) or DEFAULT_SOURCES

    try:
        page = await service.search(
            request,
            query=query,
            limit=limit_value,
            offset=offset_value,
            sources=resolved_sources,
        )
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Please provide valid search parameters.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.search",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
            retry_url=str(request.url),
            retry_target="#hx-soulseek-downloads",
            retry_label_key="soulseek.retry",
        )
    except Exception:
        logger.exception("ui.fragment.search")
        log_event(
            logger,
            "ui.fragment.search",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Search failed due to an unexpected error.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_search_results_context(
        request,
        page=page,
        query=query,
        sources=resolved_sources,
        csrf_token=csrf_token,
    )
    log_event(
        logger,
        "ui.fragment.search",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    response = templates.TemplateResponse(
        request,
        "partials/search_results.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/search", include_in_schema=False)
async def search_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    if not session.features.soulseek:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_search_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/search.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/search/results",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def search_results(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SearchUiService = Depends(get_search_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    return await _render_search_results_fragment(
        request,
        session,
        service,
        raw_query=values.get("query", [""])[0],
        raw_limit=values.get("limit", [""])[0],
        raw_offset=values.get("offset", [""])[0],
        raw_sources=values.get("sources", []),
    )


@router.get("/search/results", include_in_schema=False)
async def search_results_get(
    request: Request,
    query: str = Query(default=""),
    limit: str = Query(default=""),
    offset: str = Query(default=""),
    sources: Sequence[str] | None = Query(default=None),
    session: UiSession = Depends(require_role("operator")),
    service: SearchUiService = Depends(get_search_ui_service),
) -> Response:
    """Serve search results via GET for HTMX pagination links."""
    return await _render_search_results_fragment(
        request,
        session,
        service,
        raw_query=query,
        raw_limit=limit,
        raw_offset=offset,
        raw_sources=sources or (),
    )


@router.post(
    "/search/download",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def search_download_action(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    download_service: DownloadService = Depends(get_download_service),
) -> Response:
    if not session.features.soulseek:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    username = values.get("username", [""])[0].strip()
    files_raw = values.get("files", [""])[0]
    identifier = values.get("identifier", [""])[0]

    if not username or not files_raw:
        return _render_alert_fragment(
            request,
            "Missing download selection details.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        decoded_files = json.loads(files_raw)
    except json.JSONDecodeError:
        return _render_alert_fragment(
            request,
            "Unable to parse the selected download details.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(decoded_files, dict):
        files_data = [dict(decoded_files)]
    elif isinstance(decoded_files, list):
        files_data = [dict(item) for item in decoded_files if isinstance(item, dict)]
    else:
        files_data = []

    if not files_data:
        return _render_alert_fragment(
            request,
            "No valid download files were provided.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        payload = SoulseekDownloadRequest.model_validate(
            {
                "username": username,
                "files": files_data,
            }
        )
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Unable to queue the download request.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    worker = getattr(request.app.state, "sync_worker", None)
    try:
        await download_service.queue_downloads(payload, worker=worker)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.search.download",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            identifier=identifier or None,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.search.download")
        log_event(
            logger,
            "ui.fragment.search.download",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            identifier=identifier or None,
        )
        return _render_alert_fragment(
            request,
            "Failed to queue the download request.",
        )

    first_file = payload.files[0]
    filename = first_file.resolved_filename
    alert = AlertMessage(
        level="success",
        text=f"Queued download request for {filename}.",
    )
    context = {"request": request, "alerts": (alert,)}
    log_event(
        logger,
        "ui.fragment.search.download",
        component="ui.router",
        status="success",
        role=session.role,
        username=payload.username,
        count=len(payload.files),
        identifier=identifier or None,
    )
    return templates.TemplateResponse(
        request,
        "partials/alerts_fragment.j2",
        context,
    )


__all__ = ["router"]
