"""Utility functions for formatting values in UI contexts."""

from __future__ import annotations

from datetime import datetime

_DISPLAY_FORMAT = "%Y-%m-%d %H:%M"


def format_datetime_display(value: datetime | None) -> str:
    """Return a human friendly timestamp for UI tables.

    The result omits seconds to keep the layout compact and converts aware
    datetimes to the local timezone for display. Missing values yield an empty
    string.
    """

    if value is None:
        return ""
    if value.tzinfo is not None:
        display_value = value.astimezone()
    else:
        display_value = value
    trimmed = display_value.replace(second=0, microsecond=0)
    return trimmed.strftime(_DISPLAY_FORMAT)
