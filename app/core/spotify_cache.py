"""Cache handler storing Spotify OAuth tokens inside the settings table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from spotipy.oauth2 import CacheHandler

from app.db import session_scope
from app.logging import get_logger
from app.models import Setting

__all__ = ["SettingsCacheHandler"]

_logger = get_logger(__name__)

_TOKEN_CACHE_KEY = "SPOTIFY_TOKEN_INFO"


class SettingsCacheHandler(CacheHandler):
    """Persist Spotipy token information in the shared settings store."""

    def __init__(self, *, key: str = _TOKEN_CACHE_KEY) -> None:
        self._key = key

    def get_cached_token(self) -> Mapping[str, Any] | None:
        with session_scope() as session:
            record = (
                session.query(Setting).filter(Setting.key == self._key).one_or_none()
            )
            if record is None or not record.value:
                return None
            try:
                payload = json.loads(record.value)
            except json.JSONDecodeError:
                _logger.warning(
                    "Failed to decode cached Spotify token; ignoring.",
                    extra={"event": "spotify.token_cache.decode_failed"},
                )
                return None
            if not isinstance(payload, Mapping):
                return None
            return payload

    def save_token_to_cache(self, token_info: Mapping[str, Any]) -> None:
        sanitized = dict(token_info)
        if "expires_at" not in sanitized and "expires_in" in sanitized:
            try:
                expires_in = int(sanitized["expires_in"])
            except (TypeError, ValueError):
                expires_in = 0
            sanitized["expires_at"] = int(
                datetime.now(timezone.utc).timestamp() + max(0, expires_in)
            )
        serialized = json.dumps(sanitized)
        with session_scope() as session:
            record = (
                session.query(Setting).filter(Setting.key == self._key).one_or_none()
            )
            now = datetime.utcnow()
            if record is None:
                session.add(
                    Setting(
                        key=self._key,
                        value=serialized,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                record.value = serialized
                record.updated_at = now

