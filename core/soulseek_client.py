"""Client abstraction for interacting with the Soulseek network."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List


@dataclass
class TrackResult:
    """Represents a single track entry returned by a Soulseek search."""

    username: str
    filename: str
    size: int
    bitrate: int | None = None
    length: int | None = None

    def to_dict(self) -> dict:
        """Return a dictionary representation without ``None`` values."""

        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


class SoulseekClient:
    """Asynchronous client used to communicate with a Soulseek daemon."""

    async def search(self, query: str) -> List[TrackResult]:
        """Search Soulseek for the provided query.

        The default implementation returns an empty result set. Projects that
        integrate an actual Soulseek backend should subclass ``SoulseekClient``
        and override this method.
        """

        return []

    async def download(self, username: str, filename: str, size: int = 0) -> bool:
        """Initiate a download for a specific track from a Soulseek user.

        The base implementation returns ``True`` so that components interacting
        with the client can operate without a concrete Soulseek backend. Override
        this method to provide the real download integration.
        """

        return True


__all__ = ["SoulseekClient", "TrackResult"]
