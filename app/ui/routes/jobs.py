from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import AppConfig
from app.dependencies import get_app_config
from app.errors import AppError
from app.logging_events import log_event
from app.ui.context.jobs import build_jobs_fragment_context, build_jobs_page_context
from app.ui.csrf import attach_csrf_cookie, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _render_alert_fragment,
    _resolve_live_updates_mode,
    logger,
    templates,
)
from app.ui.services import JobsUiService, get_jobs_ui_service
from app.ui.session import UiSession, require_role

router = APIRouter()


@router.get("/jobs", include_in_schema=False, name="jobs_page")
async def jobs_page(
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
    context = build_jobs_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        live_updates_mode=_resolve_live_updates_mode(config),
    )
    response = templates.TemplateResponse(
        request,
        "pages/jobs.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/jobs/table", include_in_schema=False)
async def jobs_table(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: JobsUiService = Depends(get_jobs_ui_service),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    try:
        jobs = await service.list_jobs(request)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.jobs",
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
        logger.exception("ui.fragment.jobs")
        log_event(
            logger,
            "ui.fragment.jobs",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load orchestrator jobs.",
        )

    context = build_jobs_fragment_context(
        request,
        jobs=jobs,
    )
    log_event(
        logger,
        "ui.fragment.jobs",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/jobs_fragment.j2",
        context,
    )


__all__ = ["router"]
