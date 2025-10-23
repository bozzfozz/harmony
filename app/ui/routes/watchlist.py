from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import ValidationError

from app.config import AppConfig
from app.dependencies import get_app_config
from app.errors import AppError
from app.logging_events import log_event
from app.schemas.watchlist import (
    WatchlistEntryCreate,
    WatchlistPauseRequest,
    WatchlistPriorityUpdate,
)
from app.ui.context.operations import (
    build_watchlist_fragment_context,
    build_watchlist_page_context,
)
from app.ui.csrf import attach_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _parse_form_body,
    _render_alert_fragment,
    _resolve_live_updates_mode,
    logger,
    templates,
)
from app.ui.services import WatchlistUiService, get_watchlist_ui_service
from app.ui.session import UiSession, require_role

router = APIRouter()


@router.get("/watchlist", include_in_schema=False, name="watchlist_page")
async def watchlist_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_watchlist_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        live_updates_mode=_resolve_live_updates_mode(config),
    )
    response = templates.TemplateResponse(
        request,
        "pages/watchlist.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/watchlist/table", include_in_schema=False)
async def watchlist_table(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    csrf_token = request.cookies.get("csrftoken", "")
    limit = request.query_params.get("limit")
    offset = request.query_params.get("offset")
    try:
        table = await service.list_entries_async(request)
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

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
        csrf_token=csrf_token,
        limit=limit,
        offset=offset,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


@router.post(
    "/watchlist/{artist_key}/priority",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
    name="watchlist_priority_update",
)
async def watchlist_priority_update(
    request: Request,
    artist_key: str,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    priority_raw = values.get("priority", "")
    limit = values.get("limit")
    offset = values.get("offset")

    try:
        payload = WatchlistPriorityUpdate.model_validate({"priority": priority_raw})
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Please provide a valid priority value.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        table = await service.update_priority(
            request,
            artist_key=artist_key,
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
        logger.exception("ui.fragment.watchlist.priority")
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
            "Failed to update the watchlist entry.",
        )

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
        csrf_token=request.cookies.get("csrftoken", ""),
        limit=limit,
        offset=offset,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


@router.post(
    "/watchlist/{artist_key}/pause",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
    name="watchlist_pause",
)
async def watchlist_pause(
    request: Request,
    artist_key: str,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    limit = values.get("limit")
    offset = values.get("offset")
    pause_payload_raw = {
        "reason": values.get("reason"),
        "resume_at": values.get("resume_at") or None,
    }

    try:
        pause_payload = WatchlistPauseRequest.model_validate(pause_payload_raw)
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Please provide a valid resume date and time.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        table = await service.pause_entry(
            request,
            artist_key=artist_key,
            reason=pause_payload.reason,
            resume_at=pause_payload.resume_at,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            action="pause",
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.watchlist.pause")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            action="pause",
        )
        return _render_alert_fragment(
            request,
            "Failed to pause the watchlist entry.",
        )

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
        csrf_token=request.cookies.get("csrftoken", ""),
        limit=limit,
        offset=offset,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        action="pause",
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


@router.post(
    "/watchlist/{artist_key}/resume",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
    name="watchlist_resume",
)
async def watchlist_resume(
    request: Request,
    artist_key: str,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    limit = values.get("limit")
    offset = values.get("offset")

    try:
        table = await service.resume_entry(request, artist_key=artist_key)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            action="resume",
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.watchlist.resume")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            action="resume",
        )
        return _render_alert_fragment(
            request,
            "Failed to resume the watchlist entry.",
        )

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
        csrf_token=request.cookies.get("csrftoken", ""),
        limit=limit,
        offset=offset,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        action="resume",
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


@router.post(
    "/watchlist/{artist_key}/delete",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
    name="watchlist_delete",
)
async def watchlist_delete(
    request: Request,
    artist_key: str,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    limit = values.get("limit")
    offset = values.get("offset")

    try:
        table = await service.delete_entry(request, artist_key=artist_key)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            action="delete",
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.watchlist.delete")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            action="delete",
        )
        return _render_alert_fragment(
            request,
            "Failed to remove the watchlist entry.",
        )

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
        csrf_token=request.cookies.get("csrftoken", ""),
        limit=limit,
        offset=offset,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        action="delete",
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


@router.post(
    "/watchlist",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def watchlist_create(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    payload_data = {
        "artist_key": values.get("artist_key", ""),
        "priority": values.get("priority") or None,
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
        table = await service.create_entry(
            request,
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

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
        csrf_token=request.cookies.get("csrftoken", ""),
        limit=None,
        offset=None,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


__all__ = ["router"]
