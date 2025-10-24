from datetime import UTC, datetime

from starlette.requests import Request

from app.ui.context.common import KpiCard, SidebarItem, SidebarSection
from app.ui.context.downloads import build_downloads_page_context
from app.ui.context.jobs import build_jobs_page_context
from app.ui.context.operations import (
    build_activity_page_context,
    build_operations_page_context,
    build_watchlist_page_context,
)
from app.ui.session import UiFeatures, UiSession


def _make_session(*, role: str = "operator", dlq: bool = True) -> UiSession:
    now = datetime.now(tz=UTC)
    features = UiFeatures(spotify=True, soulseek=True, dlq=dlq, imports=True)
    return UiSession(
        identifier="session",  # pragma: no cover - deterministic identifier for tests
        role=role,
        features=features,
        fingerprint="fingerprint",
        issued_at=now,
        last_seen_at=now,
    )


def _make_request(path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


def test_operations_page_context_includes_fragments_for_enabled_features() -> None:
    request = _make_request("/ui/operations")
    session = _make_session()

    context = build_operations_page_context(request, session=session, csrf_token="token")

    layout = context["layout"]
    assert layout.page_id == "operations"
    assert layout.live_updates_mode == "polling"
    assert layout.live_updates_source is None
    downloads_fragment = context["downloads_fragment"]
    assert downloads_fragment is not None
    assert downloads_fragment.poll_interval_seconds == 15
    assert downloads_fragment.target == "#hx-downloads-table"
    jobs_fragment = context["jobs_fragment"]
    assert jobs_fragment is not None
    assert jobs_fragment.poll_interval_seconds == 15
    assert context["watchlist_fragment"].poll_interval_seconds == 30
    assert context["activity_fragment"].poll_interval_seconds == 60
    assert context["dashboard_url"] == "/ui"
    kpi_cards = context["kpi_cards"]
    assert isinstance(kpi_cards, tuple)
    assert len(kpi_cards) == 1
    card = kpi_cards[0]
    assert isinstance(card, KpiCard)
    assert card.value == "Polling"
    assert card.badge_label == "Interval"
    assert card.badge_variant == "muted"
    sidebar_sections = context["sidebar_sections"]
    assert isinstance(sidebar_sections, tuple)
    assert all(isinstance(section, SidebarSection) for section in sidebar_sections)
    navigation_section = next(
        section for section in sidebar_sections if section.identifier == "operations-navigation"
    )
    assert any(
        isinstance(item, SidebarItem) and item.href == "/ui/downloads"
        for item in navigation_section.items
    )
    assert any(item.href == "/ui/jobs" for item in navigation_section.items)
    assert any(item.href == "/ui/watchlist" for item in navigation_section.items)
    assert any(item.href == "/ui/activity" for item in navigation_section.items)
    live_updates_section = next(
        section for section in sidebar_sections if section.identifier == "operations-live-updates"
    )
    assert "HTMX polling" in (live_updates_section.description or "")


def test_operations_page_context_omits_dlq_sections_when_disabled() -> None:
    request = _make_request("/ui/operations")
    session = _make_session(dlq=False)

    context = build_operations_page_context(request, session=session, csrf_token="token")

    assert context["downloads_fragment"] is None
    assert context["jobs_fragment"] is None
    assert context["watchlist_fragment"].poll_interval_seconds == 30
    assert context["activity_fragment"].poll_interval_seconds == 60
    navigation_section = next(
        section
        for section in context["sidebar_sections"]
        if section.identifier == "operations-navigation"
    )
    identifiers = {item.identifier for item in navigation_section.items}
    assert "operations-downloads-link" not in identifiers
    assert "operations-jobs-link" not in identifiers
    assert "operations-watchlist-link" in identifiers
    assert "operations-activity-link" in identifiers


def test_operations_page_context_uses_sse_metadata() -> None:
    request = _make_request("/ui/operations")
    session = _make_session()

    context = build_operations_page_context(
        request,
        session=session,
        csrf_token="token",
        live_updates_mode="sse",
    )

    card = context["kpi_cards"][0]
    assert card.value == "Streaming"
    assert card.badge_label == "Real-time"
    assert card.badge_variant == "success"
    layout = context["layout"]
    assert layout.live_updates_mode == "sse"
    assert layout.live_updates_source == "/ui/events"
    live_updates_section = next(
        section
        for section in context["sidebar_sections"]
        if section.identifier == "operations-live-updates"
    )
    assert "Server-sent events" in (live_updates_section.description or "")


def test_downloads_page_context_sets_operations_navigation() -> None:
    request = _make_request("/ui/downloads")
    session = _make_session()

    context = build_downloads_page_context(request, session=session, csrf_token="token")

    layout = context["layout"]
    assert layout.page_id == "downloads"
    assert layout.live_updates_mode == "polling"
    assert layout.live_updates_source is None
    assert context["downloads_fragment"].url.endswith("/ui/downloads/table")
    navigation = context["layout"].navigation.primary
    assert any(item.href == "/ui/operations" and item.active for item in navigation)


def test_downloads_page_context_uses_sse_source() -> None:
    request = _make_request("/ui/downloads")
    session = _make_session()

    context = build_downloads_page_context(
        request,
        session=session,
        csrf_token="token",
        live_updates_mode="sse",
    )

    layout = context["layout"]
    assert layout.live_updates_mode == "sse"
    assert layout.live_updates_source == "/ui/events"
    fragment = context["downloads_fragment"]
    assert fragment.event_name == "downloads"
    assert fragment.poll_interval_seconds is None


def test_jobs_page_context_uses_sse_source() -> None:
    request = _make_request("/ui/jobs")
    session = _make_session()

    context = build_jobs_page_context(
        request,
        session=session,
        csrf_token="token",
        live_updates_mode="sse",
    )

    layout = context["layout"]
    assert layout.live_updates_mode == "sse"
    assert layout.live_updates_source == "/ui/events"
    fragment = context["jobs_fragment"]
    assert fragment.event_name == "jobs"
    assert fragment.poll_interval_seconds is None
    navigation = layout.navigation.primary
    assert any(item.href == "/ui/operations" and item.active for item in navigation)


def test_watchlist_page_context_exposes_form_fields() -> None:
    request = _make_request("/ui/watchlist")
    session = _make_session()

    context = build_watchlist_page_context(request, session=session, csrf_token="token")

    form = context["watchlist_form"]
    assert form.identifier == "watchlist-create-form"
    assert form.action == "/ui/watchlist"
    assert any(field.name == "artist_key" for field in form.fields)
    assert any(field.name == "priority" for field in form.fields)


def test_watchlist_page_context_uses_sse_source() -> None:
    request = _make_request("/ui/watchlist")
    session = _make_session()

    context = build_watchlist_page_context(
        request,
        session=session,
        csrf_token="token",
        live_updates_mode="sse",
    )

    layout = context["layout"]
    assert layout.live_updates_mode == "sse"
    assert layout.live_updates_source == "/ui/events"
    fragment = context["watchlist_fragment"]
    assert fragment.event_name == "watchlist"
    assert fragment.poll_interval_seconds is None


def test_activity_page_context_highlights_operations_navigation() -> None:
    request = _make_request("/ui/activity")
    session = _make_session(role="read_only")

    context = build_activity_page_context(request, session=session, csrf_token="token")

    assert context["layout"].page_id == "activity"
    assert context["activity_fragment"].poll_interval_seconds == 60
    # read_only role should still retain navigation context, even if the operations tab is absent
    assert context["layout"].navigation.primary[0].href == "/ui"


def test_activity_page_context_uses_sse_source() -> None:
    request = _make_request("/ui/activity")
    session = _make_session()

    context = build_activity_page_context(
        request,
        session=session,
        csrf_token="token",
        live_updates_mode="sse",
    )

    layout = context["layout"]
    assert layout.live_updates_mode == "sse"
    assert layout.live_updates_source == "/ui/events"
    fragment = context["activity_fragment"]
    assert fragment.event_name == "activity"
    assert fragment.poll_interval_seconds is None
