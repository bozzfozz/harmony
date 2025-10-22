from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.config import AppConfig
from app.dependencies import get_app_config
from app.errors import AppError
from app.logging_events import log_event
from app.ui.context.downloads import (
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

    csrf_token = request.cookies.get("csrftoken", "")
    context = build_downloads_fragment_context(
        request,
        page=page,
        csrf_token=csrf_token,
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
    status_filter_raw = values.get("status") or request.query_params.get("status")
    status_filter = (
        status_filter_raw.strip() if isinstance(status_filter_raw, str) else status_filter_raw
    )
    if isinstance(status_filter, str) and not status_filter:
        status_filter = None

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

    csrf_token = request.cookies.get("csrftoken", "")
    context = build_downloads_fragment_context(
        request,
        page=page,
        csrf_token=csrf_token,
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


@router.post(
    "/downloads/{download_id}/retry",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
    name="downloads_retry",
)
async def downloads_retry(
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
    limit_value, offset_value, include_all = _extract_download_refresh_params(request, values)
    status_filter_raw = values.get("status") or request.query_params.get("status")
    status_filter = (
        status_filter_raw.strip() if isinstance(status_filter_raw, str) else status_filter_raw
    )
    if isinstance(status_filter, str) and not status_filter:
        status_filter = None

    try:
        page = await service.retry_download(
            download_id=download_id,
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.downloads.retry",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.downloads.retry")
        log_event(
            logger,
            "ui.fragment.downloads.retry",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to retry the download.",
        )

    csrf_token = request.cookies.get("csrftoken", "")
    context = build_downloads_fragment_context(
        request,
        page=page,
        csrf_token=csrf_token,
        status_filter=status_filter,
        include_all=include_all,
    )
    log_event(
        logger,
        "ui.fragment.downloads.retry",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        download_id=download_id,
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
    )
    return templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )


@router.delete(
    "/downloads/{download_id}",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
    name="downloads_cancel",
)
async def downloads_cancel(
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
    limit_value, offset_value, include_all = _extract_download_refresh_params(request, values)
    status_filter_raw = values.get("status") or request.query_params.get("status")
    status_filter = (
        status_filter_raw.strip() if isinstance(status_filter_raw, str) else status_filter_raw
    )
    if isinstance(status_filter, str) and not status_filter:
        status_filter = None

    try:
        page = await service.cancel_download(
            download_id=download_id,
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.downloads.cancel",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.downloads.cancel")
        log_event(
            logger,
            "ui.fragment.downloads.cancel",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to cancel the download.",
        )

    csrf_token = request.cookies.get("csrftoken", "")
    context = build_downloads_fragment_context(
        request,
        page=page,
        csrf_token=csrf_token,
        status_filter=status_filter,
        include_all=include_all,
    )
    log_event(
        logger,
        "ui.fragment.downloads.cancel",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        download_id=download_id,
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
    )
    return templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )


@router.post(
    "/downloads/export",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
    name="downloads_export",
)
async def downloads_export(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    values = _parse_form_body(await request.body())
    format_value = (values.get("format") or "csv").strip().lower()
    status_filter = (values.get("status") or "").strip() or None
    from_value = values.get("from") or None
    to_value = values.get("to") or None

    try:
        response = service.export_downloads(
            format=format_value,
            status_filter=status_filter,
            from_time=from_value,
            to_time=to_value,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.downloads.export",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("ui.fragment.downloads.export")
        log_event(
            logger,
            "ui.fragment.downloads.export",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export downloads.",
        ) from exc

    log_event(
        logger,
        "ui.fragment.downloads.export",
        component="ui.router",
        status="success",
        role=session.role,
        format=format_value,
        status_filter=status_filter,
    )

    if hasattr(response, "headers"):
        disposition = response.headers.get("Content-Disposition")
        if not disposition:
            filename = "downloads.csv" if format_value == "csv" else "downloads.json"
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


__all__ = ["router"]
