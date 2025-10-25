"""UI service for settings management and preferences."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import SessionCallable, run_session
from app.dependencies import get_db, get_session_runner
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

T = TypeVar("T")

SessionRunner = Callable[[SessionCallable[T]], Awaitable[T]]


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

    def __init__(
        self,
        *,
        session: Session,
        session_runner: SessionRunner[Any] | None = None,
    ) -> None:
        self._session = session

        async def default_runner(func: SessionCallable[Any]) -> Any:
            return await run_session(func)

        self._run_session: SessionRunner[Any] = session_runner or default_runner

    def list_settings(self) -> SettingsOverview:
        overview = self._list_settings(self._session)
        self._log_settings_overview(overview)
        return overview

    async def list_settings_async(self) -> SettingsOverview:
        overview = await self._run_session(self._list_settings)
        self._log_settings_overview(overview)
        return overview

    def save_setting(self, *, key: str, value: str | None) -> SettingsOverview:
        overview = self._save_setting(self._session, key=key, value=value)
        self._log_setting_saved(key, value)
        return overview

    async def save_setting_async(self, *, key: str, value: str | None) -> SettingsOverview:
        def operation(session: Session) -> SettingsOverview:
            return self._save_setting(session, key=key, value=value)

        overview = await self._run_session(operation)
        self._log_setting_saved(key, value)
        return overview

    def list_history(self) -> SettingsHistoryTable:
        table = self._list_history(self._session)
        self._log_history(table)
        return table

    async def list_history_async(self) -> SettingsHistoryTable:
        table = await self._run_session(self._list_history)
        self._log_history(table)
        return table

    def list_artist_preferences(self) -> ArtistPreferenceTable:
        table = self._list_artist_preferences(self._session)
        self._log_artist_preferences(table)
        return table

    async def list_artist_preferences_async(self) -> ArtistPreferenceTable:
        table = await self._run_session(self._list_artist_preferences)
        self._log_artist_preferences(table)
        return table

    def add_or_update_artist_preference(
        self,
        *,
        artist_id: str,
        release_id: str,
        selected: bool,
    ) -> ArtistPreferenceTable:
        table = self._add_or_update_artist_preference(
            self._session,
            artist_id=artist_id,
            release_id=release_id,
            selected=selected,
        )
        self._log_artist_preference_saved(artist_id, release_id, selected)
        return table

    async def add_or_update_artist_preference_async(
        self,
        *,
        artist_id: str,
        release_id: str,
        selected: bool,
    ) -> ArtistPreferenceTable:
        def operation(session: Session) -> ArtistPreferenceTable:
            return self._add_or_update_artist_preference(
                session,
                artist_id=artist_id,
                release_id=release_id,
                selected=selected,
            )

        table = await self._run_session(operation)
        self._log_artist_preference_saved(artist_id, release_id, selected)
        return table

    def remove_artist_preference(
        self,
        *,
        artist_id: str,
        release_id: str,
    ) -> ArtistPreferenceTable:
        table = self._remove_artist_preference(
            self._session,
            artist_id=artist_id,
            release_id=release_id,
        )
        self._log_artist_preference_removed(artist_id, release_id)
        return table

    async def remove_artist_preference_async(
        self,
        *,
        artist_id: str,
        release_id: str,
    ) -> ArtistPreferenceTable:
        def operation(session: Session) -> ArtistPreferenceTable:
            return self._remove_artist_preference(
                session,
                artist_id=artist_id,
                release_id=release_id,
            )

        table = await self._run_session(operation)
        self._log_artist_preference_removed(artist_id, release_id)
        return table

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

    def _list_settings(self, session: Session) -> SettingsOverview:
        response = fetch_settings(session=session)
        return self._build_overview(response)

    def _save_setting(
        self,
        session: Session,
        *,
        key: str,
        value: str | None,
    ) -> SettingsOverview:
        payload = SettingsPayload(key=key, value=value)
        response = persist_setting(payload=payload, session=session)
        return self._build_overview(response)

    def _list_history(self, session: Session) -> SettingsHistoryTable:
        history = fetch_history(session=session)
        rows = tuple(
            SettingsHistoryRow(
                key=entry.key,
                old_value=entry.old_value,
                new_value=entry.new_value,
                changed_at=entry.changed_at,
            )
            for entry in history.history
        )
        return SettingsHistoryTable(rows=rows)

    def _list_artist_preferences(self, session: Session) -> ArtistPreferenceTable:
        preferences = fetch_artist_preferences(session=session)
        rows = tuple(
            ArtistPreferenceRow(
                artist_id=entry.artist_id,
                release_id=entry.release_id,
                selected=entry.selected,
            )
            for entry in preferences.preferences
        )
        return ArtistPreferenceTable(rows=rows)

    def _load_artist_preferences(self, session: Session) -> Sequence[ArtistPreferenceRow]:
        table = self._list_artist_preferences(session)
        return table.rows

    def _add_or_update_artist_preference(
        self,
        session: Session,
        *,
        artist_id: str,
        release_id: str,
        selected: bool,
    ) -> ArtistPreferenceTable:
        current = self._load_artist_preferences(session)
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
        persist_artist_preferences(payload=payload, session=session)
        return self._list_artist_preferences(session)

    def _remove_artist_preference(
        self,
        session: Session,
        *,
        artist_id: str,
        release_id: str,
    ) -> ArtistPreferenceTable:
        current = self._load_artist_preferences(session)
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
        persist_artist_preferences(payload=payload, session=session)
        return self._list_artist_preferences(session)

    def _log_settings_overview(self, overview: SettingsOverview) -> None:
        logger.debug(
            "settings.ui.list",
            extra={"count": len(overview.rows)},
        )

    def _log_setting_saved(self, key: str, value: str | None) -> None:
        logger.info(
            "settings.ui.save",
            extra={"key": key, "has_value": value is not None},
        )

    def _log_history(self, table: SettingsHistoryTable) -> None:
        logger.debug("settings.ui.history", extra={"count": len(table.rows)})

    def _log_artist_preferences(self, table: ArtistPreferenceTable) -> None:
        logger.debug(
            "settings.ui.artist_preferences",
            extra={"count": len(table.rows)},
        )

    def _log_artist_preference_saved(self, artist_id: str, release_id: str, selected: bool) -> None:
        logger.info(
            "settings.ui.artist_preferences.save",
            extra={
                "artist_id": artist_id,
                "release_id": release_id,
                "selected": selected,
            },
        )

    def _log_artist_preference_removed(self, artist_id: str, release_id: str) -> None:
        logger.info(
            "settings.ui.artist_preferences.remove",
            extra={"artist_id": artist_id, "release_id": release_id},
        )


def get_settings_ui_service(
    session: Session = Depends(get_db),
    session_runner: SessionRunner[Any] = Depends(get_session_runner),
) -> SettingsUiService:
    return SettingsUiService(session=session, session_runner=session_runner)


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
