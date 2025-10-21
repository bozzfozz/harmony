from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.config import AppConfig
from app.dependencies import get_app_config
from app.errors import AppError
from app.logging_events import log_event
from app.ui.context.operations import (
    build_downloads_fragment_context,
    build_downloads_page_context,
)
from app.ui.csrf import attach_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _extract_download_refresh_params,
    _parse_form_body,
    _render_alert_fragment,
    _resolve_live_updates_mode,
    logger,
    templates,
)
from app.ui.services import DownloadsUiService, get_downloads_ui_service
from app.ui.session import UiSession, require_role

router = APIRouter()


@router.get("/downloads", include_in_schema=False, name="downloads_page")
async def downloads_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_downloads_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        live_updates_mode=_resolve_live_updates_mode(config),
    )
    response = templates.TemplateResponse(
        request,
        "pages/downloads.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/downloads/table", include_in_schema=False)
async def downloads_table(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_all: bool = Query(False, alias="all"),
    status_filter: str | None = Query(None, alias="status"),
    session: UiSession = Depends(require_role("operator")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    try:
        page = service.list_downloads(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.downloads",
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
        logger.exception("ui.fragment.downloads")
        log_event(
            logger,
            "ui.fragment.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load download entries.",
        )

    context = build_downloads_fragment_context(
        request,
        page=page,
        status_filter=status_filter,
        include_all=include_all,
    )
    log_event(
        logger,
        "ui.fragment.downloads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )


@router.post(
    "/downloads/{download_id}/priority",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def downloads_priority_update(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_role("operator")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    values = _parse_form_body(await request.body())
    priority_raw = values.get("priority", "")
    try:
        priority_value = int(priority_raw.strip())
    except ValueError:
        return _render_alert_fragment(
            request,
            "Please provide a numeric priority value.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    limit_value, offset_value, include_all = _extract_download_refresh_params(request, values)
    status_filter = values.get("status") or request.query_params.get("status")

    try:
        service.update_priority(
            download_id=download_id,
            priority=priority_value,
        )
        page = service.list_downloads(
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.downloads",
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
        logger.exception("ui.fragment.downloads.priority")
        log_event(
            logger,
            "ui.fragment.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Failed to update the download priority.",
        )

    context = build_downloads_fragment_context(
        request,
        page=page,
        status_filter=status_filter,
        include_all=include_all,
    )
    log_event(
        logger,
        "ui.fragment.downloads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        download_id=download_id,
        priority=priority_value,
    )
    return templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )


__all__ = ["router"]
