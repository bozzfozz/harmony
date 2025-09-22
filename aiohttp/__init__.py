from __future__ import annotations

from typing import Any


class _StubResponse:
    status: int = 500

    async def __aenter__(self) -> "_StubResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - stub
        return None

    async def json(self) -> Any:  # pragma: no cover - stub
        return {}

    async def text(self) -> str:  # pragma: no cover - stub
        return ""


class ClientSession:
    async def __aenter__(self) -> "ClientSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - stub
        return None

    def request(self, *args: Any, **kwargs: Any) -> _StubResponse:
        return _StubResponse()


__all__ = ["ClientSession"]
