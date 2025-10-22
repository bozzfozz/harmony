from __future__ import annotations

from typing import Literal

from fastapi import Request

from app.ui.session import UiSession

from .base import (
    AsyncFragment,
    LayoutContext,
    MetaTag,
    _build_primary_navigation,
    _safe_url_for,
)
from .common import SidebarItem, SidebarSection

_OPERATIONS_NAV_TITLE = "Operations overview"
_OPERATIONS_LIVE_UPDATES_TITLE = "Live updates"
_DOWNLOADS_LINK_LABEL = "View download queue"
_JOBS_LINK_LABEL = "View orchestrator jobs"
_WATCHLIST_LINK_LABEL = "Manage watchlist"
_ACTIVITY_LINK_LABEL = "View activity log"
_LIVE_UPDATES_STREAMING_DESCRIPTION = "Server-sent events keep this overview in sync in real time."
_LIVE_UPDATES_POLLING_DESCRIPTION = "HTMX polling refreshes the overview on a schedule."


def build_operations_layout(
    session: UiSession,
    *,
    page_id: str,
    csrf_token: str,
    live_updates_mode: Literal["polling", "sse"] = "polling",
    active_nav: str = "operations",
) -> LayoutContext:
    """Construct the base layout for operations pages and sub-pages."""

    use_sse = live_updates_mode == "sse"
    return LayoutContext(
        page_id=page_id,
        role=session.role,
        navigation=_build_primary_navigation(session, active=active_nav),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
        live_updates_mode=live_updates_mode,
        live_updates_source="/ui/events" if use_sse else None,
    )


def _build_operations_navigation_section(
    *,
    downloads_url: str | None,
    jobs_url: str | None,
    watchlist_url: str | None,
    activity_url: str | None,
) -> SidebarSection | None:
    items: list[SidebarItem] = []

    if downloads_url:
        items.append(
            SidebarItem(
                identifier="operations-downloads-link",
                label=_DOWNLOADS_LINK_LABEL,
                href=downloads_url,
                test_id="operations-downloads-link",
            )
        )
    if jobs_url:
        items.append(
            SidebarItem(
                identifier="operations-jobs-link",
                label=_JOBS_LINK_LABEL,
                href=jobs_url,
                test_id="operations-jobs-link",
            )
        )
    if watchlist_url:
        items.append(
            SidebarItem(
                identifier="operations-watchlist-link",
                label=_WATCHLIST_LINK_LABEL,
                href=watchlist_url,
                test_id="operations-watchlist-link",
            )
        )
    if activity_url:
        items.append(
            SidebarItem(
                identifier="operations-activity-link",
                label=_ACTIVITY_LINK_LABEL,
                href=activity_url,
                test_id="operations-activity-link",
            )
        )

    if not items:
        return None

    return SidebarSection(
        identifier="operations-navigation",
        title=_OPERATIONS_NAV_TITLE,
        items=tuple(items),
    )


def _build_operations_live_updates_section(
    live_updates_mode: Literal["polling", "sse"],
) -> SidebarSection:
    description = (
        _LIVE_UPDATES_STREAMING_DESCRIPTION
        if live_updates_mode == "sse"
        else _LIVE_UPDATES_POLLING_DESCRIPTION
    )
    return SidebarSection(
        identifier="operations-live-updates",
        title=_OPERATIONS_LIVE_UPDATES_TITLE,
        description=description,
    )


def build_operations_sidebar_sections(
    *,
    live_updates_mode: Literal["polling", "sse"],
    downloads_url: str | None,
    jobs_url: str | None,
    watchlist_url: str | None,
    activity_url: str | None,
) -> tuple[SidebarSection, ...]:
    """Assemble shared sidebar sections for operations-related pages."""

    sections: list[SidebarSection] = []

    navigation = _build_operations_navigation_section(
        downloads_url=downloads_url,
        jobs_url=jobs_url,
        watchlist_url=watchlist_url,
        activity_url=activity_url,
    )
    if navigation is not None:
        sections.append(navigation)

    sections.append(_build_operations_live_updates_section(live_updates_mode))

    return tuple(sections)


def build_downloads_async_fragment(
    request: Request,
    *,
    use_sse: bool,
    load_event: str = "load",
) -> AsyncFragment:
    """Create the downloads table async fragment definition."""

    return AsyncFragment(
        identifier="hx-downloads-table",
        url=_safe_url_for(request, "downloads_table", "/ui/downloads/table"),
        target="#hx-downloads-table",
        load_event=load_event,
        poll_interval_seconds=None if use_sse else 15,
        loading_key="downloads",
        event_name="downloads" if use_sse else None,
    )


def build_jobs_async_fragment(
    request: Request,
    *,
    use_sse: bool,
    load_event: str = "load",
) -> AsyncFragment:
    """Create the jobs table async fragment definition."""

    return AsyncFragment(
        identifier="hx-jobs-table",
        url=_safe_url_for(request, "jobs_table", "/ui/jobs/table"),
        target="#hx-jobs-table",
        load_event=load_event,
        poll_interval_seconds=None if use_sse else 15,
        loading_key="jobs",
        event_name="jobs" if use_sse else None,
    )


__all__ = [
    "build_operations_layout",
    "build_operations_sidebar_sections",
    "build_downloads_async_fragment",
    "build_jobs_async_fragment",
]
