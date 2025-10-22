from fastapi import APIRouter, Depends, Query, Request, Response

from app.config import AppConfig
from app.dependencies import get_app_config
from app.errors import AppError
from app.logging_events import log_event
from app.ui.context.operations import (
    build_activity_fragment_context,
    build_activity_page_context,
)
from app.ui.csrf import attach_csrf_cookie, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _render_alert_fragment,
    _resolve_live_updates_mode,
    logger,
    templates,
)
from app.ui.services import ActivityUiService, get_activity_ui_service
from app.ui.session import UiSession, require_session

router = APIRouter()


@router.get("/activity", include_in_schema=False, name="activity_page")
async def activity_page(
    request: Request,
    session: UiSession = Depends(require_session),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_activity_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        live_updates_mode=_resolve_live_updates_mode(config),
    )
    response = templates.TemplateResponse(
        request,
        "pages/activity.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/activity/table", include_in_schema=False)
async def activity_table(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    type_filter: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
    session: UiSession = Depends(require_session),
    service: ActivityUiService = Depends(get_activity_ui_service),
) -> Response:
    try:
        page = await service.list_activity_async(
            limit=limit,
            offset=offset,
            type_filter=type_filter,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.activity",
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
        logger.exception("ui.fragment.activity", extra={"limit": limit, "offset": offset})
        log_event(
            logger,
            "ui.fragment.activity",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load activity entries.",
        )

    context = build_activity_fragment_context(
        request,
        items=page.items,
        limit=page.limit,
        offset=page.offset,
        total_count=page.total_count,
        type_filter=page.type_filter,
        status_filter=page.status_filter,
    )
    log_event(
        logger,
        "ui.fragment.activity",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/activity_table.j2",
        context,
    )


__all__ = ["router"]
