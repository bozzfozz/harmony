from datetime import datetime, timezone

from starlette.requests import Request

from app.ui.context.admin import build_admin_page_context
from app.ui.context.base import CallToActionCard
from app.ui.session import UiFeatures, UiSession


def _make_session(*, role: str = "admin") -> UiSession:
    now = datetime.now(tz=timezone.utc)
    features = UiFeatures(spotify=True, soulseek=True, dlq=True, imports=True)
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


def test_admin_page_context_sets_navigation_and_meta() -> None:
    request = _make_request("/ui/admin")
    session = _make_session()

    context = build_admin_page_context(request, session=session, csrf_token="token")

    layout = context["layout"]
    assert layout.page_id == "admin"
    assert layout.role == "admin"
    assert any(item.href == "/ui/admin" and item.active for item in layout.navigation.primary)
    meta = layout.head_meta
    assert meta
    assert meta[0].name == "csrf-token"
    assert meta[0].content == "token"
    assert context["csrf_token"] == "token"


def test_admin_page_context_exposes_call_to_actions() -> None:
    request = _make_request("/ui/admin")
    session = _make_session()

    context = build_admin_page_context(request, session=session, csrf_token="token")

    cards = context["call_to_actions"]
    assert isinstance(cards, tuple)
    assert all(isinstance(card, CallToActionCard) for card in cards)
    assert {card.href for card in cards} == {"/ui/system", "/ui/settings"}
    assert {card.link_label_key for card in cards} == {"admin.system.link", "admin.settings.link"}
    for card in cards:
        assert card.identifier.startswith("admin-")
        assert card.title_key.startswith("admin.")
        assert card.description_key.startswith("admin.")
        assert card.link_test_id
