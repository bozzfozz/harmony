from datetime import datetime, timezone
from types import SimpleNamespace

from starlette.requests import Request

from app.ui.context.base import LayoutContext, TableCellForm
from app.ui.context.settings import (
    build_settings_artist_preferences_fragment_context,
    build_settings_form_fragment_context,
    build_settings_history_fragment_context,
    build_settings_page_context,
)
from app.ui.services.settings import (
    ArtistPreferenceRow,
    SettingRow,
    SettingsHistoryRow,
    SettingsOverview,
)
from app.ui.session import UiFeatures, UiSession


def _make_request() -> Request:
    scope = {"type": "http", "method": "GET", "path": "/ui/settings", "headers": []}
    return Request(scope)


def _make_session(role: str = "admin") -> UiSession:
    now = datetime.now(tz=timezone.utc)
    features = UiFeatures(spotify=True, soulseek=True, dlq=True, imports=True)
    return UiSession(
        identifier="session-id",
        role=role,
        features=features,
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )


def test_build_settings_page_context_sets_navigation() -> None:
    request = _make_request()
    session = _make_session()
    overview = SettingsOverview(
        rows=(
            SettingRow(key="alpha", value="1", has_override=True),
            SettingRow(key="beta", value=None, has_override=False),
        ),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    context = build_settings_page_context(
        request,
        session=session,
        csrf_token="token",
        overview=overview,
    )

    layout = context["layout"]
    assert isinstance(layout, LayoutContext)
    assert layout.page_id == "settings"
    assert any(item.href == "/ui/admin" and item.active for item in layout.navigation.primary)
    assert context["settings_form"].identifier == "settings-update-form"
    assert context["settings_table"].identifier == "settings-table"
    assert context["settings_updated_at_display"]


def test_build_settings_form_fragment_context_reuses_components() -> None:
    request = _make_request()
    overview = SettingsOverview(
        rows=(SettingRow(key="alpha", value="1", has_override=True),),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    fragment = build_settings_form_fragment_context(request, overview=overview)

    assert fragment["settings_form"].identifier == "settings-update-form"
    assert fragment["settings_table"].rows[0].cells[0].text == "alpha"


def test_build_settings_history_fragment_context_formats_rows() -> None:
    request = _make_request()
    rows = (
        SettingsHistoryRow(
            key="alpha",
            old_value="1",
            new_value=None,
            changed_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
    )

    context = build_settings_history_fragment_context(request, rows=rows)

    table = context["fragment"].table
    assert table.identifier == "settings-history-table"
    first_row = table.rows[0]
    assert first_row.cells[0].text == "alpha"
    assert first_row.cells[1].text == "1"


def test_build_settings_artist_preferences_fragment_context_builds_forms() -> None:
    request = _make_request()
    rows = (ArtistPreferenceRow(artist_id="alpha", release_id="one", selected=True),)

    context = build_settings_artist_preferences_fragment_context(
        request,
        rows=rows,
        csrf_token="token",
    )

    fragment = context["fragment"]
    assert fragment.identifier == "hx-settings-artist-preferences"
    actions_cell = fragment.table.rows[0].cells[3]
    assert actions_cell.forms
    toggle_form = actions_cell.forms[0]
    assert isinstance(toggle_form, TableCellForm)
    assert toggle_form.hidden_fields["artist_id"] == "alpha"
    assert toggle_form.hidden_fields["selected"] == "false"
    add_form = context["add_form"]
    assert add_form.identifier == "settings-artist-preferences-add"
