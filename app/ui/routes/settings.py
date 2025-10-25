from dataclasses import replace
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.logging_events import log_event
from app.ui.context.base import AlertMessage, LayoutContext
from app.ui.context.settings import (
    build_settings_artist_preferences_fragment_context,
    build_settings_form_fragment_context,
    build_settings_history_fragment_context,
    build_settings_page_context,
)
from app.ui.csrf import attach_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _parse_form_body,
    _render_alert_fragment,
    logger,
    templates,
)
from app.ui.services import (
    ArtistPreferenceTable,
    SettingsOverview,
    SettingsUiService,
    get_settings_ui_service,
)
from app.ui.session import UiSession, require_role

router = APIRouter()


@router.get("/settings", include_in_schema=False, name="settings_page")
async def settings_page(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    try:
        overview = await service.list_settings_async()
    except Exception:
        logger.exception("ui.page.settings")
        overview = SettingsOverview(rows=(), updated_at=datetime.utcnow())
        context = build_settings_page_context(
            request,
            session=session,
            csrf_token=csrf_token,
            overview=overview,
        )
        alert = AlertMessage(
            level="error",
            text="Unable to load settings. Please try again shortly.",
        )
        layout: LayoutContext = context["layout"]
        context["layout"] = replace(layout, alerts=(alert,))
        status_value = "error"
    else:
        context = build_settings_page_context(
            request,
            session=session,
            csrf_token=csrf_token,
            overview=overview,
        )
        status_value = "success"

    response = templates.TemplateResponse(
        request,
        "pages/settings.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)

    log_event(
        logger,
        "ui.page.settings",
        component="ui.router",
        status=status_value,
        role=session.role,
        count=len(overview.rows),
    )
    return response


@router.get(
    "/settings/history",
    include_in_schema=False,
    name="settings_history_fragment",
)
async def settings_history_fragment(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    try:
        history = await service.list_history_async()
    except Exception:
        logger.exception("ui.fragment.settings.history")
        return _render_alert_fragment(
            request,
            "Unable to load the settings history.",
            retry_url="/ui/settings/history",
            retry_target="#hx-settings-history",
        )

    context = build_settings_history_fragment_context(
        request,
        rows=history.rows,
    )
    log_event(
        logger,
        "ui.fragment.settings.history",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/settings_history.j2",
        context,
    )


@router.get(
    "/settings/artist-preferences",
    include_in_schema=False,
    name="settings_artist_preferences_fragment",
)
async def settings_artist_preferences_fragment(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    try:
        table = await service.list_artist_preferences_async()
    except Exception:
        logger.exception("ui.fragment.settings.artist_preferences")
        return _render_alert_fragment(
            request,
            "Unable to load artist preferences.",
            retry_url="/ui/settings/artist-preferences",
            retry_target="#hx-settings-artist-preferences",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_settings_artist_preferences_fragment_context(
        request,
        rows=table.rows,
        csrf_token=csrf_token,
    )
    log_event(
        logger,
        "ui.fragment.settings.artist_preferences",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    response = templates.TemplateResponse(
        request,
        "partials/settings_artist_preferences.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/settings",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def settings_save(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    key = values.get("key", "").strip()
    if not key:
        return _render_alert_fragment(
            request,
            "Please provide a setting key.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    raw_value = values.get("value")
    value = raw_value.strip() if raw_value is not None else None
    if value == "":
        value = None

    try:
        overview = await service.save_setting_async(key=key, value=value)
    except HTTPException as exc:
        return _render_alert_fragment(
            request,
            exc.detail if isinstance(exc.detail, str) else "Failed to save the setting.",
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("ui.fragment.settings.save")
        return _render_alert_fragment(
            request,
            "Failed to save the setting.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_settings_form_fragment_context(
        request,
        overview=overview,
    )
    context["csrf_token"] = csrf_token
    log_event(
        logger,
        "ui.fragment.settings.save",
        component="ui.router",
        status="success",
        role=session.role,
        key=key,
    )
    response = templates.TemplateResponse(
        request,
        "partials/settings_form.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/settings/artist-preferences",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def settings_artist_preferences_save(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    action = values.get("action", "").strip().lower()
    artist_id = values.get("artist_id", "").strip()
    release_id = values.get("release_id", "").strip()

    if action == "add":
        if not artist_id or not release_id:
            return _render_alert_fragment(
                request,
                "Artist and release identifiers are required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        selected_raw = values.get("selected", "")
        selected = selected_raw.lower() in {"on", "true", "1", "yes"}

        async def handler() -> ArtistPreferenceTable:
            return await service.add_or_update_artist_preference_async(
                artist_id=artist_id,
                release_id=release_id,
                selected=selected,
            )

    elif action == "toggle":
        if not artist_id or not release_id:
            return _render_alert_fragment(
                request,
                "Artist and release identifiers are required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        selected_raw = values.get("selected", "false")
        selected = selected_raw.lower() in {"true", "1", "yes", "on"}

        async def handler() -> ArtistPreferenceTable:
            return await service.add_or_update_artist_preference_async(
                artist_id=artist_id,
                release_id=release_id,
                selected=selected,
            )

    elif action == "remove":
        if not artist_id or not release_id:
            return _render_alert_fragment(
                request,
                "Artist and release identifiers are required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        async def handler() -> ArtistPreferenceTable:
            return await service.remove_artist_preference_async(
                artist_id=artist_id,
                release_id=release_id,
            )

    else:
        return _render_alert_fragment(
            request,
            "Unsupported action.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        table = await handler()
    except HTTPException as exc:
        return _render_alert_fragment(
            request,
            exc.detail if isinstance(exc.detail, str) else "Failed to update artist preferences.",
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("ui.fragment.settings.artist_preferences.save")
        return _render_alert_fragment(
            request,
            "Failed to update artist preferences.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_settings_artist_preferences_fragment_context(
        request,
        rows=table.rows,
        csrf_token=csrf_token,
    )
    log_event(
        logger,
        "ui.fragment.settings.artist_preferences.save",
        component="ui.router",
        status="success",
        role=session.role,
        action=action,
    )
    response = templates.TemplateResponse(
        request,
        "partials/settings_artist_preferences.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


__all__ = ["router"]
