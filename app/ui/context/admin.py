from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request

from app.ui.session import UiSession

from .base import CallToActionCard, LayoutContext, MetaTag, _build_primary_navigation


def build_admin_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="admin",
        role=session.role,
        navigation=_build_primary_navigation(session, active="admin"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    call_to_actions = (
        CallToActionCard(
            identifier="admin-system-card",
            title_key="admin.system.title",
            description_key="admin.system.description",
            href="/ui/system",
            link_label_key="admin.system.link",
            link_test_id="admin-system-link",
        ),
        CallToActionCard(
            identifier="admin-settings-card",
            title_key="admin.settings.title",
            description_key="admin.settings.description",
            href="/ui/settings",
            link_label_key="admin.settings.link",
            link_test_id="admin-settings-link",
        ),
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "call_to_actions": call_to_actions,
    }


__all__ = ["build_admin_page_context"]
