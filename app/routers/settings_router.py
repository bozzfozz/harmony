"""Settings management endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Setting
from app.schemas import SettingsPayload, SettingsResponse

router = APIRouter()


@router.get("", response_model=SettingsResponse)
def get_settings(session: Session = Depends(get_db)) -> SettingsResponse:
    settings = session.execute(select(Setting)).scalars().all()
    settings_dict = {setting.key: setting.value for setting in settings}
    updated_at = max((setting.updated_at or setting.created_at for setting in settings), default=datetime.utcnow())
    return SettingsResponse(settings=settings_dict, updated_at=updated_at)


@router.post("", response_model=SettingsResponse)
def update_setting(payload: SettingsPayload, session: Session = Depends(get_db)) -> SettingsResponse:
    if not payload.key:
        raise HTTPException(status_code=400, detail="Key must not be empty")
    setting = session.execute(select(Setting).where(Setting.key == payload.key)).scalar_one_or_none()
    now = datetime.utcnow()
    if setting is None:
        setting = Setting(key=payload.key, value=payload.value, updated_at=now)
        session.add(setting)
    else:
        setting.value = payload.value
        setting.updated_at = now
    session.commit()
    return get_settings(session)
