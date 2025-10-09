"""Settings management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_SETTINGS
from app.dependencies import get_db
from app.models import ArtistPreference, Setting, SettingHistory
from app.schemas import (
    ArtistPreferenceEntry,
    ArtistPreferencesPayload,
    ArtistPreferencesResponse,
    SettingsHistoryResponse,
    SettingsPayload,
    SettingsResponse,
)

CONFIGURATION_KEYS: Final[tuple[str, ...]] = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REDIRECT_URI",
    "PLEX_BASE_URL",
    "PLEX_TOKEN",
    "PLEX_LIBRARY",
    "SLSKD_URL",
    "SLSKD_API_KEY",
)


router = APIRouter()


@router.get("", response_model=SettingsResponse)
def get_settings(session: Session = Depends(get_db)) -> SettingsResponse:
    settings = session.execute(select(Setting)).scalars().all()
    settings_dict = {setting.key: setting.value for setting in settings}
    effective_settings = dict(DEFAULT_SETTINGS)
    effective_settings.update(settings_dict)
    for key in CONFIGURATION_KEYS:
        effective_settings.setdefault(key, None)
    updated_at = max(
        (setting.updated_at or setting.created_at for setting in settings),
        default=datetime.utcnow(),
    )
    return SettingsResponse(settings=effective_settings, updated_at=updated_at)


@router.post("", response_model=SettingsResponse)
def update_setting(
    payload: SettingsPayload, session: Session = Depends(get_db)
) -> SettingsResponse:
    if not payload.key:
        raise HTTPException(status_code=400, detail="Key must not be empty")
    setting = session.execute(
        select(Setting).where(Setting.key == payload.key)
    ).scalar_one_or_none()
    now = datetime.utcnow()

    history_entry = SettingHistory(
        key=payload.key,
        old_value=setting.value if setting is not None else None,
        new_value=payload.value,
        changed_at=now,
    )
    session.add(history_entry)

    if setting is None:
        setting = Setting(key=payload.key, value=payload.value, updated_at=now)
        session.add(setting)
    else:
        setting.value = payload.value
        setting.updated_at = now
    session.commit()
    return get_settings(session)


@router.get("/history", response_model=SettingsHistoryResponse)
def get_settings_history(session: Session = Depends(get_db)) -> SettingsHistoryResponse:
    history_entries = (
        session.execute(
            select(SettingHistory).order_by(SettingHistory.changed_at.desc()).limit(50)
        )
        .scalars()
        .all()
    )
    return SettingsHistoryResponse(history=history_entries)


def _list_artist_preferences(session: Session) -> list[ArtistPreferenceEntry]:
    entries = (
        session.execute(
            select(ArtistPreference).order_by(
                ArtistPreference.artist_id, ArtistPreference.release_id
            )
        )
        .scalars()
        .all()
    )
    return [
        ArtistPreferenceEntry(
            artist_id=entry.artist_id,
            release_id=entry.release_id,
            selected=entry.selected,
        )
        for entry in entries
    ]


@router.get("/artist-preferences", response_model=ArtistPreferencesResponse)
def get_artist_preferences(
    session: Session = Depends(get_db),
) -> ArtistPreferencesResponse:
    preferences = _list_artist_preferences(session)
    return ArtistPreferencesResponse(preferences=preferences)


@router.post("/artist-preferences", response_model=ArtistPreferencesResponse)
def save_artist_preferences(
    payload: ArtistPreferencesPayload,
    session: Session = Depends(get_db),
) -> ArtistPreferencesResponse:
    if not payload.preferences:
        session.execute(delete(ArtistPreference))
        session.commit()
        return ArtistPreferencesResponse(preferences=[])

    seen: set[tuple[str, str]] = set()
    for preference in payload.preferences:
        artist_id = preference.artist_id.strip()
        release_id = preference.release_id.strip()
        if not artist_id or not release_id:
            raise HTTPException(
                status_code=400, detail="artist_id and release_id must not be empty"
            )
        key = (artist_id, release_id)
        if key in seen:
            continue
        seen.add(key)
        record = session.get(
            ArtistPreference,
            {"artist_id": artist_id, "release_id": release_id},
        )
        if record is None:
            record = ArtistPreference(
                artist_id=artist_id,
                release_id=release_id,
                selected=preference.selected,
            )
            session.add(record)
        else:
            record.selected = preference.selected

    session.commit()
    preferences = _list_artist_preferences(session)
    return ArtistPreferencesResponse(preferences=preferences)
