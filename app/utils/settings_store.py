"""Utility helpers for reading and writing dynamic settings."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db import session_scope
from app.models import Setting


def write_setting(key: str, value: str) -> None:
    """Persist a string value to the settings table."""

    now = datetime.utcnow()
    with session_scope() as session:
        setting = (
            session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
        )
        if setting is None:
            session.add(
                Setting(
                    key=key,
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            setting.value = value
            setting.updated_at = now


def read_setting(key: str) -> Optional[str]:
    """Return the stored value for ``key`` if present."""

    with session_scope() as session:
        setting = (
            session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
        )
        if setting is None:
            return None
        return setting.value


def increment_counter(key: str, *, amount: int = 1) -> int:
    """Increment an integer counter stored as a setting and return the new value."""

    if amount == 0:
        current = read_setting(key)
        return int(current) if current and current.isdigit() else 0

    with session_scope() as session:
        setting = (
            session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
        )
        now = datetime.utcnow()
        if setting is None:
            new_value = amount
            session.add(
                Setting(
                    key=key,
                    value=str(new_value),
                    created_at=now,
                    updated_at=now,
                )
            )
            return new_value

        try:
            current_value = int(setting.value or 0)
        except (TypeError, ValueError):
            current_value = 0

        new_value = current_value + amount
        setting.value = str(new_value)
        setting.updated_at = now
        return new_value
