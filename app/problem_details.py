"""Problem Details helpers for RFC 7807 responses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProblemDetailException(Exception):
    """Exception used to signal RFC 7807 problem detail responses."""

    status_code: int
    title: str
    detail: str
    type: str = "about:blank"

    def to_dict(self) -> dict[str, int | str]:
        """Return the serialisable representation of the problem detail."""

        return {
            "type": self.type,
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
        }
