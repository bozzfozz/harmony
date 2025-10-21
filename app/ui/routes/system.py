from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.errors import AppError
from app.ui.context import (
    attach_secret_result,
    build_system_integrations_context,
    build_system_liveness_context,
    build_system_page_context,
    build_system_readiness_context,
    build_system_secret_card_context,
    build_system_secret_cards,
    build_system_service_health_context,
    select_system_secret_card,
)
from app.ui.csrf import attach_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _parse_form_body,
    _render_alert_fragment,
    logger,
    templates,
)
from app.ui.services import SystemUiService, get_system_ui_service
from app.ui.session import UiSession, require_admin_with_feature, require_role

router = APIRouter()


@router.get("/system", include_in_schema=False, name="system_page")
async def system_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_system_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/system.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get(
    "/system/liveness",
    include_in_schema=False,
    name="system_liveness_fragment",
)
async def system_liveness_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        summary = await service.fetch_liveness(request)
    except AppError as exc:
        message = exc.message or "Unable to load liveness information."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/liveness",
            retry_target="#hx-system-liveness",
        )
    except Exception:
        logger.exception("system.ui.liveness.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load liveness information.",
            retry_url="/ui/system/liveness",
            retry_target="#hx-system-liveness",
        )

    context = build_system_liveness_context(request, summary=summary)
    return templates.TemplateResponse(
        request,
        "partials/system_liveness.j2",
        context,
    )


@router.get(
    "/system/readiness",
    include_in_schema=False,
    name="system_readiness_fragment",
)
async def system_readiness_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        summary = await service.fetch_readiness(request)
    except AppError as exc:
        message = exc.message or "Unable to load readiness information."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/readiness",
            retry_target="#hx-system-readiness",
        )
    except Exception:
        logger.exception("system.ui.readiness.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load readiness information.",
            retry_url="/ui/system/readiness",
            retry_target="#hx-system-readiness",
        )

    context = build_system_readiness_context(request, summary=summary)
    return templates.TemplateResponse(
        request,
        "partials/system_readiness.j2",
        context,
    )


@router.get(
    "/system/integrations",
    include_in_schema=False,
    name="system_integrations_fragment",
)
async def system_integrations_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        summary = await service.fetch_integrations()
    except AppError as exc:
        message = exc.message or "Unable to load integration status."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/integrations",
            retry_target="#hx-system-integrations",
        )
    except Exception:
        logger.exception("system.ui.integrations.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load integration status.",
            retry_url="/ui/system/integrations",
            retry_target="#hx-system-integrations",
        )

    context = build_system_integrations_context(request, summary=summary)
    return templates.TemplateResponse(
        request,
        "partials/system_integrations.j2",
        context,
    )


@router.get(
    "/system/services",
    include_in_schema=False,
    name="system_services_fragment",
)
async def system_services_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        badges = await service.fetch_service_badges()
    except AppError as exc:
        message = exc.message or "Failed to load service health."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/services",
            retry_target="#hx-system-services",
        )
    except Exception:
        logger.exception("system.ui.services.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load service health.",
            retry_url="/ui/system/services",
            retry_target="#hx-system-services",
        )

    context = build_system_service_health_context(request, badges=badges)
    return templates.TemplateResponse(
        request,
        "partials/system_services.j2",
        context,
    )


@router.get(
    "/system/secrets/{provider}",
    include_in_schema=False,
    name="system_secret_card",
)
async def system_secret_card(
    provider: str,
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    cards = build_system_secret_cards()
    card = select_system_secret_card(cards, provider)
    if card is None:
        return _render_alert_fragment(
            request,
            "Unknown secret provider requested.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_system_secret_card_context(
        request,
        card=card,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "partials/system_secret_card.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/system/secrets/{provider}",
    include_in_schema=False,
    name="system_validate_secret",
    dependencies=[Depends(enforce_csrf)],
)
async def system_validate_secret(
    provider: str,
    request: Request,
    session: UiSession = Depends(require_admin_with_feature("imports")),
    service: SystemUiService = Depends(get_system_ui_service),
    db_session: Session = Depends(get_db),
) -> Response:
    cards = build_system_secret_cards()
    base_card = select_system_secret_card(cards, provider)
    if base_card is None:
        return _render_alert_fragment(
            request,
            "Unknown secret provider requested.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    target_selector = f"#{base_card.target_id}"

    form_values = _parse_form_body(await request.body())
    override_value = form_values.get("value", "")
    override_value = override_value.strip() or None

    try:
        result = await service.validate_secret(
            request,
            provider=provider,
            override=override_value,
            session=db_session,
        )
    except AppError as exc:
        message = exc.message or "Secret validation failed."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url=f"/ui/system/secrets/{base_card.provider}",
            retry_target=target_selector,
        )
    except Exception:
        logger.exception("system.ui.secret.validate")
        return _render_alert_fragment(
            request,
            "Secret validation failed.",
            retry_url=f"/ui/system/secrets/{base_card.provider}",
            retry_target=target_selector,
        )

    updated_card = attach_secret_result(base_card, result)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_system_secret_card_context(
        request,
        card=updated_card,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "partials/system_secret_card.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


__all__ = ["router", "get_system_ui_service"]
