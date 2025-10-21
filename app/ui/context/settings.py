from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from fastapi import Request

from app.ui.formatters import format_datetime_display
from app.ui.session import UiSession

from .base import (
    AsyncFragment,
    FormDefinition,
    FormField,
    LayoutContext,
    MetaTag,
    TableCell,
    TableCellForm,
    TableDefinition,
    TableFragment,
    TableRow,
    _build_primary_navigation,
    _safe_url_for,
)

if TYPE_CHECKING:
    from app.ui.services import (
        ArtistPreferenceRow,
        SettingRow,
        SettingsHistoryRow,
        SettingsOverview,
    )


def _build_settings_form_definition() -> FormDefinition:
    return FormDefinition(
        identifier="settings-update-form",
        method="post",
        action="/ui/settings",
        submit_label_key="settings.save",
        fields=(
            FormField(
                name="key",
                input_type="text",
                label_key="settings.key",
                required=True,
            ),
            FormField(
                name="value",
                input_type="text",
                label_key="settings.value",
            ),
        ),
    )


def _build_settings_table(rows: Sequence["SettingRow"]) -> TableDefinition:
    table_rows: list[TableRow] = []
    for row in rows:
        value_cell = (
            TableCell(text=row.value)
            if row.value not in (None, "")
            else TableCell(text_key="settings.value.unset")
        )
        status_key = (
            "settings.override.present" if row.has_override else "settings.override.missing"
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.key),
                    value_cell,
                    TableCell(text_key=status_key),
                ),
                test_id=f"setting-row-{row.key}",
            )
        )
    return TableDefinition(
        identifier="settings-table",
        column_keys=("settings.key", "settings.value", "settings.override"),
        rows=tuple(table_rows),
        caption_key="settings.table.caption",
    )


def _build_settings_form_components(
    overview: "SettingsOverview",
) -> tuple[FormDefinition, TableDefinition, str]:
    form = _build_settings_form_definition()
    table = _build_settings_table(overview.rows)
    updated_display = format_datetime_display(overview.updated_at)
    return form, table, updated_display


def build_settings_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    overview: "SettingsOverview",
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="settings",
        role=session.role,
        navigation=_build_primary_navigation(session, active="admin"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    settings_form, settings_table, updated_display = _build_settings_form_components(overview)

    history_url = _safe_url_for(request, "settings_history_fragment", "/ui/settings/history")
    preferences_url = _safe_url_for(
        request, "settings_artist_preferences_fragment", "/ui/settings/artist-preferences"
    )

    history_fragment = AsyncFragment(
        identifier="hx-settings-history",
        url=history_url,
        target="#hx-settings-history",
        loading_key="settings-history",
    )
    history_form = FormDefinition(
        identifier="settings-history-refresh",
        method="get",
        action=history_url,
        submit_label_key="settings.history.refresh",
    )

    artist_fragment = AsyncFragment(
        identifier="hx-settings-artist-preferences",
        url=preferences_url,
        target="#hx-settings-artist-preferences",
        loading_key="settings-artist-preferences",
    )
    artist_form = FormDefinition(
        identifier="settings-artist-preferences-refresh",
        method="get",
        action=preferences_url,
        submit_label_key="settings.artist_preferences.refresh",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "settings_form": settings_form,
        "settings_table": settings_table,
        "settings_updated_at_display": updated_display,
        "history_fragment": history_fragment,
        "history_refresh_form": history_form,
        "artist_preferences_fragment": artist_fragment,
        "artist_preferences_refresh_form": artist_form,
    }


def build_settings_form_fragment_context(
    request: Request,
    *,
    overview: "SettingsOverview",
) -> Mapping[str, Any]:
    settings_form, settings_table, updated_display = _build_settings_form_components(overview)
    return {
        "request": request,
        "settings_form": settings_form,
        "settings_table": settings_table,
        "settings_updated_at_display": updated_display,
    }


def build_settings_history_fragment_context(
    request: Request,
    *,
    rows: Sequence["SettingsHistoryRow"],
) -> Mapping[str, Any]:
    table_rows: list[TableRow] = []
    for entry in rows:
        old_cell = TableCell(text=entry.old_value or "")
        new_cell = TableCell(text=entry.new_value or "")
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=entry.key),
                    old_cell,
                    new_cell,
                    TableCell(text=format_datetime_display(entry.changed_at)),
                ),
            )
        )

    table = TableDefinition(
        identifier="settings-history-table",
        column_keys=(
            "settings.history.key",
            "settings.history.old",
            "settings.history.new",
            "settings.history.changed",
        ),
        rows=tuple(table_rows),
        caption_key="settings.history.caption",
    )

    fragment = TableFragment(
        identifier="hx-settings-history",
        table=table,
        empty_state_key="settings-history",
        data_attributes={"count": str(len(table_rows))},
    )

    return {"request": request, "fragment": fragment}


def build_settings_artist_preferences_fragment_context(
    request: Request,
    *,
    rows: Sequence["ArtistPreferenceRow"],
    csrf_token: str,
) -> Mapping[str, Any]:
    table_rows: list[TableRow] = []
    for row in rows:
        state_key = (
            "settings.artist_preferences.state.enabled"
            if row.selected
            else "settings.artist_preferences.state.disabled"
        )
        target_state = "false" if row.selected else "true"
        toggle_label = (
            "settings.artist_preferences.disable"
            if row.selected
            else "settings.artist_preferences.enable"
        )
        toggle_form = TableCellForm(
            action="/ui/settings/artist-preferences",
            method="post",
            submit_label_key=toggle_label,
            hidden_fields={
                "csrftoken": csrf_token,
                "action": "toggle",
                "artist_id": row.artist_id,
                "release_id": row.release_id,
                "selected": target_state,
            },
            hx_target="#hx-settings-artist-preferences",
            hx_swap="outerHTML",
            test_id=f"artist-preference-toggle-{row.artist_id}-{row.release_id}",
        )
        remove_form = TableCellForm(
            action="/ui/settings/artist-preferences",
            method="post",
            submit_label_key="settings.artist_preferences.remove",
            hidden_fields={
                "csrftoken": csrf_token,
                "action": "remove",
                "artist_id": row.artist_id,
                "release_id": row.release_id,
            },
            hx_target="#hx-settings-artist-preferences",
            hx_swap="outerHTML",
            test_id=f"artist-preference-remove-{row.artist_id}-{row.release_id}",
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.artist_id),
                    TableCell(text=row.release_id),
                    TableCell(text_key=state_key),
                    TableCell(forms=(toggle_form, remove_form)),
                ),
            )
        )

    table = TableDefinition(
        identifier="settings-artist-preferences-table",
        column_keys=(
            "settings.artist_preferences.artist",
            "settings.artist_preferences.release",
            "settings.artist_preferences.selected",
            "settings.artist_preferences.actions",
        ),
        rows=tuple(table_rows),
        caption_key="settings.artist_preferences.caption",
    )

    fragment = TableFragment(
        identifier="hx-settings-artist-preferences",
        table=table,
        empty_state_key="settings-artist-preferences",
        data_attributes={"count": str(len(table_rows))},
    )

    add_form = FormDefinition(
        identifier="settings-artist-preferences-add",
        method="post",
        action="/ui/settings/artist-preferences",
        submit_label_key="settings.artist_preferences.add",
        fields=(
            FormField(
                name="artist_id",
                input_type="text",
                label_key="settings.artist_preferences.artist",
                required=True,
            ),
            FormField(
                name="release_id",
                input_type="text",
                label_key="settings.artist_preferences.release",
                required=True,
            ),
            FormField(
                name="selected",
                input_type="checkbox",
                label_key="settings.artist_preferences.selected",
            ),
        ),
    )

    return {
        "request": request,
        "fragment": fragment,
        "add_form": add_form,
        "csrf_token": csrf_token,
    }


__all__ = [
    "build_settings_page_context",
    "build_settings_form_fragment_context",
    "build_settings_history_fragment_context",
    "build_settings_artist_preferences_fragment_context",
]
