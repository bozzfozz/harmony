from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.logging_events import log_event
from app.ui.context.auth import build_login_page_context
from app.ui.context.dashboard import build_dashboard_page_context
from app.ui.csrf import (
    attach_csrf_cookie,
    clear_csrf_cookie,
    enforce_csrf,
    get_csrf_manager,
)
from app.ui.routes.shared import logger, templates
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
