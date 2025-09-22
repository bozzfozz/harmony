"""Settings management endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Final

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Setting, SettingHistory
from app.schemas import SettingsHistoryResponse, SettingsPayload, SettingsResponse

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
    for key in CONFIGURATION_KEYS:
        settings_dict.setdefault(key, None)
    updated_at = max((setting.updated_at or setting.created_at for setting in settings), default=datetime.utcnow())
    return SettingsResponse(settings=settings_dict, updated_at=updated_at)


@router.post("", response_model=SettingsResponse)
def update_setting(payload: SettingsPayload, session: Session = Depends(get_db)) -> SettingsResponse:
    if not payload.key:
        raise HTTPException(status_code=400, detail="Key must not be empty")
    setting = session.execute(select(Setting).where(Setting.key == payload.key)).scalar_one_or_none()
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
