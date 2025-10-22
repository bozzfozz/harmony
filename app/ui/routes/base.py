from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.errors import AppError
from app.logging_events import log_event
from app.ui.context.auth import build_login_page_context
from app.ui.context.dashboard import (
    build_dashboard_health_fragment_context,
    build_dashboard_page_context,
    build_dashboard_status_fragment_context,
    build_dashboard_workers_fragment_context,
)
from app.ui.csrf import (
    attach_csrf_cookie,
    clear_csrf_cookie,
    enforce_csrf,
    get_csrf_manager,
)
from app.ui.routes.shared import _render_alert_fragment, logger, templates
from app.ui.services import DashboardUiService, get_dashboard_ui_service
from app.ui.session import (
    UiSession,
    attach_session_cookie,
    clear_session_cookie,
    clear_spotify_job_state,
    get_session_manager,
    require_session,
)

router = APIRouter()


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


@router.get(
    "/dashboard/status",
    include_in_schema=False,
    name="dashboard_status_fragment",
)
async def dashboard_status_fragment(
    request: Request,
    session: UiSession = Depends(require_session),
    service: DashboardUiService = Depends(get_dashboard_ui_service),
) -> Response:
    try:
        summary = await service.fetch_status(request)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.dashboard_status",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/dashboard/status",
            retry_target="#hx-dashboard-status",
        )
    except Exception:
        logger.exception("ui.fragment.dashboard_status")
        log_event(
            logger,
            "ui.fragment.dashboard_status",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load dashboard status.",
            retry_url="/ui/dashboard/status",
            retry_target="#hx-dashboard-status",
        )

    context = build_dashboard_status_fragment_context(request, summary=summary)
    log_event(
        logger,
        "ui.fragment.dashboard_status",
        component="ui.router",
        status="success",
        role=session.role,
        connections=len(summary.connections),
        readiness_issues=len(summary.readiness_issues),
    )
    return templates.TemplateResponse(
        request,
        "partials/dashboard_status.j2",
        context,
    )


@router.get(
    "/dashboard/health",
    include_in_schema=False,
    name="dashboard_health_fragment",
)
async def dashboard_health_fragment(
    request: Request,
    session: UiSession = Depends(require_session),
    service: DashboardUiService = Depends(get_dashboard_ui_service),
) -> Response:
    try:
        summary = await service.fetch_health(request)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.dashboard_health",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/dashboard/health",
            retry_target="#hx-dashboard-health",
        )
    except Exception:
        logger.exception("ui.fragment.dashboard_health")
        log_event(
            logger,
            "ui.fragment.dashboard_health",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load dashboard health information.",
            retry_url="/ui/dashboard/health",
            retry_target="#hx-dashboard-health",
        )

    context = build_dashboard_health_fragment_context(request, summary=summary)
    log_event(
        logger,
        "ui.fragment.dashboard_health",
        component="ui.router",
        status="success",
        role=session.role,
        issues=len(summary.issues),
    )
    return templates.TemplateResponse(
        request,
        "partials/dashboard_health.j2",
        context,
    )


@router.get(
    "/dashboard/workers",
    include_in_schema=False,
    name="dashboard_workers_fragment",
)
async def dashboard_workers_fragment(
    request: Request,
    session: UiSession = Depends(require_session),
    service: DashboardUiService = Depends(get_dashboard_ui_service),
) -> Response:
    try:
        workers = await service.fetch_workers(request)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.dashboard_workers",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/dashboard/workers",
            retry_target="#hx-dashboard-workers",
        )
    except Exception:
        logger.exception("ui.fragment.dashboard_workers")
        log_event(
            logger,
            "ui.fragment.dashboard_workers",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load worker information.",
            retry_url="/ui/dashboard/workers",
            retry_target="#hx-dashboard-workers",
        )

    context = build_dashboard_workers_fragment_context(request, workers=workers)
    log_event(
        logger,
        "ui.fragment.dashboard_workers",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["workers"]),
    )
    return templates.TemplateResponse(
        request,
        "partials/dashboard_workers.j2",
        context,
    )


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
    await clear_spotify_job_state(request, session)
    await manager.invalidate(session.identifier)
    cookies_secure = manager.security.ui_cookies_secure
    response = RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response, secure=cookies_secure)
    clear_csrf_cookie(response, secure=cookies_secure)
    response.headers.setdefault("HX-Redirect", "/ui/login")
    return response


__all__ = ["router"]
