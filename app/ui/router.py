from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.logging import get_logger
from app.logging_events import log_event
from app.ui.csrf import attach_csrf_cookie, clear_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.session import (
    UiSession,
    attach_session_cookie,
    clear_session_cookie,
    get_session_manager,
    require_session,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/ui", tags=["UI"])


def _render_login_page(error: str | None, status_code: int = status.HTTP_200_OK) -> HTMLResponse:
    error_html = ""
    if error:
        error_html = f'<p role="alert" class="error">{error}</p>'
    body = f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>Login · Harmony UI</title>
  </head>
  <body data-role=\"anonymous\">
    <header>
      <h1>Harmony Operator Console</h1>
    </header>
    <main>
      <section>
        <h2>Sign in</h2>
        {error_html}
        <form method=\"post\" action=\"/ui/login\">
          <label for=\"api_key\">API key</label>
          <input type=\"password\" name=\"api_key\" id=\"api_key\" autocomplete=\"off\" required />
          <button type=\"submit\">Login</button>
        </form>
      </section>
    </main>
  </body>
</html>"""
    return HTMLResponse(content=body, status_code=status_code)


def _render_dashboard_page(
    *,
    session: UiSession,
    csrf_token: str,
    can_operator: bool,
    can_admin: bool,
) -> HTMLResponse:
    operator_nav = ""
    operator_action = ""
    if can_operator:
        operator_nav = '<a href="/ui/operations" data-test="nav-operator">Operations</a>'
        operator_action = '<button id="operator-action" type="button">Operator action</button>'
    admin_nav = ""
    admin_action = ""
    if can_admin:
        admin_nav = '<a href="/ui/admin" data-test="nav-admin">Admin</a>'
        admin_action = '<button id="admin-action" type="button">Admin action</button>'
    body = f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>Dashboard · Harmony UI</title>
    <meta name=\"csrf-token\" content=\"{csrf_token}\" />
  </head>
  <body data-role=\"{session.role}\">
    <header>
      <h1>Harmony Operator Console</h1>
      <nav aria-label=\"Primary\">
        <a href=\"/ui\" data-test=\"nav-home\">Home</a>
        {operator_nav}
        {admin_nav}
      </nav>
      <form id=\"logout-form\" method=\"post\" action=\"/ui/logout\">
        <button type=\"submit\">Logout</button>
      </form>
    </header>
    <main>
      <section>
        <h2>Welcome</h2>
        <p id=\"session-role\" data-role=\"{session.role}\">Current role: {session.role}</p>
        <ul>
          <li data-feature=\"spotify\">Spotify tools: {"enabled" if session.features.spotify else "disabled"}</li>
          <li data-feature=\"soulseek\">Soulseek tools: {"enabled" if session.features.soulseek else "disabled"}</li>
          <li data-feature=\"dlq\">DLQ tools: {"enabled" if session.features.dlq else "disabled"}</li>
          <li data-feature=\"imports\">Imports: {"enabled" if session.features.imports else "disabled"}</li>
        </ul>
        {operator_action}
        {admin_action}
      </section>
    </main>
  </body>
</html>"""
    return HTMLResponse(content=body)


@router.get("/login", include_in_schema=False)
async def login_form(request: Request) -> Response:
    manager = get_session_manager(request)
    existing_id = request.cookies.get("ui_session")
    if existing_id:
        existing = await manager.get_session(existing_id)
        if existing is not None:
            return RedirectResponse("/ui", status_code=status.HTTP_303_SEE_OTHER)
    return _render_login_page(error=None)


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
        return _render_login_page(error=message, status_code=status_code)

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
    csrf_token_placeholder = ""
    response = _render_dashboard_page(
        session=session,
        csrf_token=csrf_token_placeholder,
        can_operator=session.allows("operator"),
        can_admin=session.allows("admin"),
    )
    csrf_token = attach_csrf_cookie(response, session, csrf_manager)
    response.body = response.body.replace(
        b'<meta name="csrf-token" content="" />',
        f'<meta name="csrf-token" content="{csrf_token}" />'.encode("utf-8"),
    )
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
