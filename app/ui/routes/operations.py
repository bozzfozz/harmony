from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.config import AppConfig
from app.dependencies import get_app_config
from app.ui.context.operations import build_operations_page_context
from app.ui.csrf import attach_csrf_cookie, get_csrf_manager
from app.ui.routes.shared import _ensure_csrf_token, _resolve_live_updates_mode, templates
from app.ui.session import UiSession, require_role

router = APIRouter()


@router.get("/operations", include_in_schema=False, name="operations_page")
async def operations_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_operations_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        live_updates_mode=_resolve_live_updates_mode(config),
    )
    response = templates.TemplateResponse(
        request,
        "pages/operations.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


__all__ = ["router"]
