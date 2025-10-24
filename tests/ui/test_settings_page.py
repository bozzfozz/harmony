from datetime import UTC, datetime
import re
from types import SimpleNamespace

from fastapi import status
from fastapi.testclient import TestClient
import pytest

from app.ui.services import get_settings_ui_service
from app.ui.services.settings import (
    ArtistPreferenceRow,
    SettingRow,
    SettingsHistoryRow,
    SettingsOverview,
)
from app.ui.session import fingerprint_api_key
from tests.ui.test_ui_auth import _assert_html_response, _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match is not None
    return match.group(1)


class _StubSettingsService:
    def __init__(self) -> None:
        now = datetime.now(tz=UTC)
        self.overview = SettingsOverview(
            rows=(
                SettingRow(key="alpha", value="1", has_override=True),
                SettingRow(key="beta", value=None, has_override=False),
            ),
            updated_at=now,
        )
        self.history_rows = (
            SettingsHistoryRow(
                key="alpha",
                old_value="1",
                new_value="2",
                changed_at=now,
            ),
        )
        self.preferences_rows = (
            ArtistPreferenceRow(artist_id="artist", release_id="release", selected=True),
        )
        self.saved_settings: list[tuple[str, str | None]] = []
        self.preference_calls: list[tuple[str, str, str | bool]] = []

    def list_settings(self) -> SettingsOverview:  # noqa: D401 - test stub
        return self.overview

    def save_setting(self, *, key: str, value: str | None) -> SettingsOverview:
        self.saved_settings.append((key, value))
        updated = SettingsOverview(
            rows=(SettingRow(key=key, value=value, has_override=value is not None),),
            updated_at=datetime.now(tz=UTC),
        )
        self.overview = updated
        return self.overview

    def list_history(self):  # noqa: D401 - test stub
        return SimpleNamespace(rows=self.history_rows)

    def list_artist_preferences(self):  # noqa: D401 - test stub
        return SimpleNamespace(rows=self.preferences_rows)

    def add_or_update_artist_preference(
        self,
        *,
        artist_id: str,
        release_id: str,
        selected: bool,
    ):
        self.preference_calls.append(("set", artist_id, release_id))
        self.preferences_rows = (
            ArtistPreferenceRow(artist_id=artist_id, release_id=release_id, selected=selected),
        )
        return SimpleNamespace(rows=self.preferences_rows)

    def remove_artist_preference(self, *, artist_id: str, release_id: str):
        self.preference_calls.append(("remove", artist_id, release_id))
        self.preferences_rows = tuple()
        return SimpleNamespace(rows=self.preferences_rows)


@pytest.mark.parametrize(
    "extra_env",
    [
        {"UI_ROLE_DEFAULT": "admin"},
        {"UI_ROLE_DEFAULT": "admin", "UI_ROLE_OVERRIDES": ""},
    ],
)
def test_settings_page_renders_for_admin(monkeypatch, extra_env) -> None:
    stub = _StubSettingsService()
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        client.app.dependency_overrides[get_settings_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/settings", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert 'id="hx-settings-form"' in html
        assert 'hx-get="/ui/settings/history"' in html
        assert 'hx-get="/ui/settings/artist-preferences"' in html
    client.app.dependency_overrides.pop(get_settings_ui_service, None)


def test_settings_page_forbidden_for_non_admin(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    env = {"UI_ROLE_OVERRIDES": f"{fingerprint}:operator"}
    with _create_client(monkeypatch, extra_env=env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/settings", headers=headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN


def test_settings_save_requires_csrf(monkeypatch) -> None:
    stub = _StubSettingsService()
    with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
        client.app.dependency_overrides[get_settings_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.post("/ui/settings", data={"key": "alpha", "value": "2"}, headers=headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    client.app.dependency_overrides.pop(get_settings_ui_service, None)


def test_settings_save_returns_partial(monkeypatch) -> None:
    stub = _StubSettingsService()
    with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
        client.app.dependency_overrides[get_settings_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        page = client.get("/ui/settings", headers=headers)
        _assert_html_response(page)
        token = _extract_csrf_token(page.text)
        cookie_header = _cookies_header(client)
        response = client.post(
            "/ui/settings",
            headers={"Cookie": cookie_header, "X-CSRF-Token": token},
            data={"key": "delta", "value": "9"},
        )
        _assert_html_response(response)
        assert 'id="hx-settings-form"' in response.text
        assert "delta" in response.text
        assert stub.saved_settings[-1] == ("delta", "9")
    client.app.dependency_overrides.pop(get_settings_ui_service, None)


def test_settings_history_fragment_returns_html(monkeypatch) -> None:
    stub = _StubSettingsService()
    with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
        client.app.dependency_overrides[get_settings_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        fragment = client.get("/ui/settings/history", headers=headers)
        _assert_html_response(fragment)
        assert "settings-history-table" in fragment.text
    client.app.dependency_overrides.pop(get_settings_ui_service, None)


def test_artist_preferences_toggle_updates(monkeypatch) -> None:
    stub = _StubSettingsService()
    with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
        client.app.dependency_overrides[get_settings_ui_service] = lambda: stub
        _login(client)
        page = client.get("/ui/settings", headers={"Cookie": _cookies_header(client)})
        _assert_html_response(page)
        token = _extract_csrf_token(page.text)
        headers = {"Cookie": _cookies_header(client), "X-CSRF-Token": token}
        response = client.post(
            "/ui/settings/artist-preferences",
            headers=headers,
            data={
                "action": "toggle",
                "artist_id": "artist",
                "release_id": "release",
                "selected": "false",
            },
        )
        _assert_html_response(response)
        assert 'id="settings-artist-preferences-table"' in response.text
        assert stub.preference_calls[-1][:2] == ("set", "artist")
    client.app.dependency_overrides.pop(get_settings_ui_service, None)
