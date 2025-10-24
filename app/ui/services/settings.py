"""UI service for settings management and preferences."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.logging import get_logger
from app.routers.settings_router import (
    get_artist_preferences as fetch_artist_preferences,
    get_settings as fetch_settings,
    get_settings_history as fetch_history,
    save_artist_preferences as persist_artist_preferences,
    update_setting as persist_setting,
)
from app.schemas import (
    ArtistPreferenceEntry,
    ArtistPreferencesPayload,
    SettingsPayload,
    SettingsResponse,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class SettingRow:
    key: str
    value: str | None
    has_override: bool


@dataclass(slots=True)
class SettingsOverview:
    rows: Sequence[SettingRow]
    updated_at: datetime


@dataclass(slots=True)
class SettingsHistoryRow:
    key: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime


@dataclass(slots=True)
class SettingsHistoryTable:
    rows: Sequence[SettingsHistoryRow]


@dataclass(slots=True)
class ArtistPreferenceRow:
    artist_id: str
    release_id: str
    selected: bool


@dataclass(slots=True)
class ArtistPreferenceTable:
    rows: Sequence[ArtistPreferenceRow]


class SettingsUiService:
    """Facade for orchestrating settings UI interactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_settings(self) -> SettingsOverview:
        response = fetch_settings(session=self._session)
        overview = self._build_overview(response)
        logger.debug(
            "settings.ui.list",
            extra={"count": len(overview.rows)},
        )
        return overview

    def save_setting(self, *, key: str, value: str | None) -> SettingsOverview:
        payload = SettingsPayload(key=key, value=value)
        response = persist_setting(payload=payload, session=self._session)
        overview = self._build_overview(response)
        logger.info(
            "settings.ui.save",
            extra={"key": key, "has_value": value is not None},
        )
        return overview

    def list_history(self) -> SettingsHistoryTable:
        history = fetch_history(session=self._session)
        rows = tuple(
            SettingsHistoryRow(
                key=entry.key,
                old_value=entry.old_value,
                new_value=entry.new_value,
                changed_at=entry.changed_at,
            )
            for entry in history.history
        )
        logger.debug("settings.ui.history", extra={"count": len(rows)})
        return SettingsHistoryTable(rows=rows)

    def list_artist_preferences(self) -> ArtistPreferenceTable:
        preferences = fetch_artist_preferences(session=self._session)
        rows = tuple(
            ArtistPreferenceRow(
                artist_id=entry.artist_id,
                release_id=entry.release_id,
                selected=entry.selected,
            )
            for entry in preferences.preferences
        )
        logger.debug("settings.ui.artist_preferences", extra={"count": len(rows)})
        return ArtistPreferenceTable(rows=rows)

    def add_or_update_artist_preference(
        self,
        *,
        artist_id: str,
        release_id: str,
        selected: bool,
    ) -> ArtistPreferenceTable:
        current = self._load_artist_preferences()
        key = (artist_id, release_id)
        entries: dict[tuple[str, str], ArtistPreferenceEntry] = {
            (row.artist_id, row.release_id): ArtistPreferenceEntry(
                artist_id=row.artist_id,
                release_id=row.release_id,
                selected=row.selected,
            )
            for row in current
        }
        entries[key] = ArtistPreferenceEntry(
            artist_id=artist_id,
            release_id=release_id,
            selected=selected,
        )
        payload = ArtistPreferencesPayload(preferences=list(entries.values()))
        persist_artist_preferences(payload=payload, session=self._session)
        logger.info(
            "settings.ui.artist_preferences.save",
            extra={"artist_id": artist_id, "release_id": release_id, "selected": selected},
        )
        return self.list_artist_preferences()

    def remove_artist_preference(
        self,
        *,
        artist_id: str,
        release_id: str,
    ) -> ArtistPreferenceTable:
        current = self._load_artist_preferences()
        payload_entries = [
            ArtistPreferenceEntry(
                artist_id=row.artist_id,
                release_id=row.release_id,
                selected=row.selected,
            )
            for row in current
            if not (row.artist_id == artist_id and row.release_id == release_id)
        ]
        payload = ArtistPreferencesPayload(preferences=payload_entries)
        persist_artist_preferences(payload=payload, session=self._session)
        logger.info(
            "settings.ui.artist_preferences.remove",
            extra={"artist_id": artist_id, "release_id": release_id},
        )
        return self.list_artist_preferences()

    def _build_overview(self, response: SettingsResponse) -> SettingsOverview:
        rows = []
        for key in sorted(response.settings.keys()):
            raw_value = response.settings[key]
            value = None if raw_value is None else str(raw_value)
            has_override = bool(value)
            rows.append(
                SettingRow(
                    key=key,
                    value=value,
                    has_override=has_override,
                )
            )
        return SettingsOverview(rows=tuple(rows), updated_at=response.updated_at)

    def _load_artist_preferences(self) -> Sequence[ArtistPreferenceRow]:
        table = self.list_artist_preferences()
        return table.rows


def get_settings_ui_service(
    session: Session = Depends(get_db),
) -> SettingsUiService:
    return SettingsUiService(session=session)


__all__ = [
    "SettingRow",
    "SettingsOverview",
    "SettingsHistoryRow",
    "SettingsHistoryTable",
    "ArtistPreferenceRow",
    "ArtistPreferenceTable",
    "SettingsUiService",
    "get_settings_ui_service",
]
