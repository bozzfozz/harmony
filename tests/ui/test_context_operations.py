from datetime import datetime, timezone

from starlette.requests import Request

from app.ui.context import (
    build_activity_page_context,
    build_downloads_page_context,
    build_operations_page_context,
    build_watchlist_page_context,
)
from app.ui.session import UiFeatures, UiSession


def _make_session(*, role: str = "operator", dlq: bool = True) -> UiSession:
    now = datetime.now(tz=timezone.utc)
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

    assert context["layout"].page_id == "operations"
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


def test_operations_page_context_omits_dlq_sections_when_disabled() -> None:
    request = _make_request("/ui/operations")
    session = _make_session(dlq=False)

    context = build_operations_page_context(request, session=session, csrf_token="token")

    assert context["downloads_fragment"] is None
    assert context["jobs_fragment"] is None
    assert context["watchlist_fragment"].poll_interval_seconds == 30
    assert context["activity_fragment"].poll_interval_seconds == 60


def test_downloads_page_context_sets_operations_navigation() -> None:
    request = _make_request("/ui/downloads")
    session = _make_session()

    context = build_downloads_page_context(request, session=session, csrf_token="token")

    assert context["layout"].page_id == "downloads"
    assert context["downloads_fragment"].url.endswith("/ui/downloads/table")
    navigation = context["layout"].navigation.primary
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


def test_activity_page_context_highlights_operations_navigation() -> None:
    request = _make_request("/ui/activity")
    session = _make_session(role="read_only")

    context = build_activity_page_context(request, session=session, csrf_token="token")

    assert context["layout"].page_id == "activity"
    assert context["activity_fragment"].poll_interval_seconds == 60
    # read_only role should still retain navigation context, even if the operations tab is absent
    assert context["layout"].navigation.primary[0].href == "/ui"
