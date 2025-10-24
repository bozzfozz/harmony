from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas import (
    ArtistPreferenceEntry,
    ArtistPreferencesResponse,
    SettingsHistoryEntry,
    SettingsHistoryResponse,
    SettingsResponse,
)
from app.ui.services.settings import (
    ArtistPreferenceRow,
    SettingsHistoryRow,
    SettingsOverview,
    SettingsUiService,
)


def _make_service(monkeypatch, *, settings=None, history=None, preferences=None):
    if settings is None:
        settings = SettingsResponse(settings={}, updated_at=datetime.now(tz=UTC))
    if history is None:
        history = SettingsHistoryResponse(history=[])
    if preferences is None:
        preferences = ArtistPreferencesResponse(preferences=[])

    monkeypatch.setattr("app.ui.services.settings.fetch_settings", lambda session: settings)
    monkeypatch.setattr("app.ui.services.settings.fetch_history", lambda session: history)
    monkeypatch.setattr(
        "app.ui.services.settings.fetch_artist_preferences",
        lambda session: preferences,
    )

    def _save_settings(payload, session):  # noqa: D401 - test helper
        return settings

    monkeypatch.setattr("app.ui.services.settings.persist_setting", _save_settings)

    def _save_preferences(payload, session):  # noqa: D401 - test helper
        nonlocal preferences
        entries = [
            ArtistPreferenceEntry(
                artist_id=item["artist_id"],
                release_id=item["release_id"],
                selected=item["selected"],
            )
            for item in payload.model_dump()["preferences"]
        ]
        preferences = ArtistPreferencesResponse(preferences=entries)
        return preferences

    monkeypatch.setattr(
        "app.ui.services.settings.persist_artist_preferences",
        _save_preferences,
    )

    return SettingsUiService(session=SimpleNamespace())


def test_list_settings_orders_rows(monkeypatch) -> None:
    response = SettingsResponse(
        settings={"b": "2", "a": "1"},
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    service = _make_service(monkeypatch, settings=response)

    overview = service.list_settings()

    assert isinstance(overview, SettingsOverview)
    assert [row.key for row in overview.rows] == ["a", "b"]
    assert overview.rows[0].value == "1"
    assert overview.rows[0].has_override is True


def test_save_setting_passes_payload(monkeypatch) -> None:
    recorded: dict[str, str | None] = {}

    def fake_update(payload, session):  # noqa: D401 - signature match
        recorded["key"] = payload.key
        recorded["value"] = payload.value
        return SettingsResponse(
            settings={payload.key: payload.value}, updated_at=datetime.now(tz=UTC)
        )

    monkeypatch.setattr("app.ui.services.settings.persist_setting", fake_update)
    service = SettingsUiService(session=SimpleNamespace())

    overview = service.save_setting(key="TEST", value="42")

    assert recorded == {"key": "TEST", "value": "42"}
    assert any(row.key == "TEST" for row in overview.rows)


def test_list_history_converts_entries(monkeypatch) -> None:
    changed_at = datetime(2024, 2, 1, 12, tzinfo=UTC)
    history = SettingsHistoryResponse(
        history=[
            SettingsHistoryEntry(
                key="TEST",
                old_value="1",
                new_value="2",
                changed_at=changed_at,
            )
        ]
    )
    service = _make_service(monkeypatch, history=history)

    table = service.list_history()

    assert len(table.rows) == 1
    row = table.rows[0]
    assert isinstance(row, SettingsHistoryRow)
    assert row.changed_at == changed_at


def test_add_artist_preference_replaces_existing(monkeypatch) -> None:
    preferences = ArtistPreferencesResponse(
        preferences=[ArtistPreferenceEntry(artist_id="alpha", release_id="one", selected=True)]
    )
    service = _make_service(monkeypatch, preferences=preferences)

    table = service.add_or_update_artist_preference(
        artist_id="alpha",
        release_id="one",
        selected=False,
    )

    assert len(table.rows) == 1
    assert isinstance(table.rows[0], ArtistPreferenceRow)
    assert table.rows[0].selected is False


def test_remove_artist_preference_filters(monkeypatch) -> None:
    preferences = ArtistPreferencesResponse(
        preferences=[
            ArtistPreferenceEntry(artist_id="alpha", release_id="one", selected=True),
            ArtistPreferenceEntry(artist_id="beta", release_id="two", selected=False),
        ]
    )
    service = _make_service(monkeypatch, preferences=preferences)

    table = service.remove_artist_preference(artist_id="alpha", release_id="one")

    assert len(table.rows) == 1
    assert table.rows[0].artist_id == "beta"
