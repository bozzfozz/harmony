"""Utility helpers for loading sensitive configuration values from storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting

_PROVIDER_SETTINGS = {
    "slskd_api_key": ("SLSKD_API_KEY", "SLSKD_URL"),
    "spotify_client_secret": ("SPOTIFY_CLIENT_SECRET", "SPOTIFY_CLIENT_ID"),
}


@dataclass(slots=True)
class SecretRecord:
    """Represents a stored secret value without exposing the payload."""

    key: str
    value: Optional[str]

    @property
    def present(self) -> bool:
        """Return whether a value is configured for the secret."""

        return bool((self.value or "").strip())

    @property
    def last4(self) -> Optional[str]:
        """Return the last four characters if a value exists."""

        if not self.present:
            return None
        trimmed = (self.value or "").strip()
        if len(trimmed) <= 4:
            return trimmed
        return trimmed[-4:]


class SecretStore:
    """Load and expose sensitive configuration values for validation flows."""

    def __init__(
        self, session: Session, *, preload: Iterable[str] | None = None
    ) -> None:
        keys = set(preload or ()) | {
            setting_key
            for values in _PROVIDER_SETTINGS.values()
            for setting_key in values
        }
        rows = session.execute(
            select(Setting.key, Setting.value).where(Setting.key.in_(keys))
        )
        self._values: MutableMapping[str, Optional[str]] = {
            key: value for key, value in rows
        }

    @classmethod
    def from_values(cls, values: Mapping[str, Optional[str]]) -> "SecretStore":
        """Create a store from an in-memory mapping (primarily for testing)."""

        instance = cls.__new__(cls)
        instance._values = dict(values)
        return instance

    def get(self, key: str) -> SecretRecord:
        """Return the stored record for a raw setting key."""

        return SecretRecord(key=key, value=self._values.get(key))

    def secret_for_provider(self, provider: str) -> SecretRecord:
        """Return the primary secret value for the given provider."""

        mapping = _PROVIDER_SETTINGS.get(provider)
        if not mapping:
            return SecretRecord(key=provider, value=None)
        key = mapping[0]
        return self.get(key)

    def dependent_setting(self, provider: str, index: int = 1) -> SecretRecord:
        """Return auxiliary settings for a provider (e.g. Spotify client ID)."""

        mapping = _PROVIDER_SETTINGS.get(provider)
        if not mapping or index >= len(mapping):
            return SecretRecord(key=f"{provider}:dep:{index}", value=None)
        key = mapping[index]
        return self.get(key)
