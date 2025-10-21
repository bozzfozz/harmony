from fastapi import APIRouter, Depends, Request, Response

from app.ui.context import build_admin_page_context
from app.ui.csrf import attach_csrf_cookie, get_csrf_manager
from app.ui.routes.shared import _ensure_csrf_token, templates
from app.ui.session import UiSession, require_role


router = APIRouter()


@router.get("/admin", include_in_schema=False, name="admin_page")
async def admin_page(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_admin_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/admin.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


__all__ = ["router"]
