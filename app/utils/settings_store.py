"""Utility helpers for reading and writing dynamic settings."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import select

from app.db import session_scope
from app.models import Setting


def _parse_counter_value(value: str | None) -> int | None:
    """Return an integer representation of a stored counter value."""

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def write_setting(key: str, value: str) -> None:
    """Persist a string value to the settings table."""

    now = datetime.utcnow()
    with session_scope() as session:
        setting = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
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


def read_setting(key: str) -> str | None:
    """Return the stored value for ``key`` if present."""

    with session_scope() as session:
        setting = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
        if setting is None:
            return None
        return setting.value


def delete_setting(key: str) -> None:
    """Remove a setting row if it exists."""

    with session_scope() as session:
        setting = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
        if setting is None:
            return
        session.delete(setting)


def ensure_default_settings(defaults: Mapping[str, str]) -> None:
    """Insert missing settings using provided defaults."""

    if not defaults:
        return

    now = datetime.utcnow()
    with session_scope() as session:
        existing_keys = set(session.execute(select(Setting.key)).scalars().all())
        for key, value in defaults.items():
            if key in existing_keys:
                continue
            session.add(
                Setting(
                    key=key,
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )


def increment_counter(key: str, *, amount: int = 1) -> int:
    """Increment an integer counter stored as a setting and return the new value.

    Passing ``amount=0`` acts as a read-only operation: the existing counter value
    is returned without mutating the backing row.  This is useful for callers that
    want to inspect a counter atomically while leaving the persisted state
    untouched and, importantly, avoids creating a new row when no counter exists
    yet.
    """

    if amount == 0:
        current = _parse_counter_value(read_setting(key))
        return current if current is not None else 0

    with session_scope() as session:
        setting = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
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

        current_value = _parse_counter_value(setting.value)
        if current_value is None:
            current_value = 0

        new_value = current_value + amount
        setting.value = str(new_value)
        setting.updated_at = now
        return new_value
