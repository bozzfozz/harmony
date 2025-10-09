"""Unit tests for the high level transfers API wrapper."""

from __future__ import annotations

import pytest

from app.core.soulseek_client import SoulseekClientError
from app.core.transfers_api import (
    TransfersApi,
    TransfersDependencyError,
    TransfersNotFoundError,
    TransfersValidationError,
)


class _StubSoulseekClient:
    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.enqueued: list[tuple[str, list[dict[str, object]]]] = []

    async def cancel_download(self, transfer_id: str) -> dict[str, object]:
        self.cancelled.append(transfer_id)
        return {"status": "cancelled", "cancelled": transfer_id}

    async def enqueue(
        self, username: str, files: list[dict[str, object]]
    ) -> dict[str, object]:
        self.enqueued.append((username, files))
        return {"job": {"id": files[0].get("download_id", "job-1")}}


@pytest.mark.asyncio
async def test_cancel_download_success() -> None:
    client = _StubSoulseekClient()
    api = TransfersApi(client)

    assert await api.cancel_download("42") is True
    assert client.cancelled == ["42"]


@pytest.mark.asyncio
async def test_cancel_download_validates_identifier() -> None:
    api = TransfersApi(_StubSoulseekClient())

    with pytest.raises(TransfersValidationError):
        await api.cancel_download("  ")

    with pytest.raises(TransfersValidationError):
        await api.cancel_download(0)


@pytest.mark.asyncio
async def test_cancel_download_maps_not_found() -> None:
    class _ErrorClient(_StubSoulseekClient):
        async def cancel_download(self, transfer_id: str) -> dict[str, object]:  # type: ignore[override]
            raise SoulseekClientError("not found", status_code=404)

    api = TransfersApi(_ErrorClient())

    with pytest.raises(TransfersNotFoundError) as exc:
        await api.cancel_download("55")

    assert exc.value.code.value == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cancel_download_maps_dependency_error() -> None:
    class _ErrorClient(_StubSoulseekClient):
        async def cancel_download(self, transfer_id: str) -> dict[str, object]:  # type: ignore[override]
            raise SoulseekClientError("boom", status_code=503)

    api = TransfersApi(_ErrorClient())

    with pytest.raises(TransfersDependencyError) as exc:
        await api.cancel_download("12")

    assert exc.value.code.value == "DEPENDENCY_ERROR"


@pytest.mark.asyncio
async def test_enqueue_success() -> None:
    client = _StubSoulseekClient()
    api = TransfersApi(client)

    identifier = await api.enqueue(
        username="alice", files=[{"download_id": 1001, "filename": "song.flac"}]
    )

    assert identifier == "1001"
    assert client.enqueued[0][0] == "alice"


@pytest.mark.asyncio
async def test_enqueue_validates_inputs() -> None:
    api = TransfersApi(_StubSoulseekClient())

    with pytest.raises(TransfersValidationError):
        await api.enqueue(username="  ", files=[{"download_id": 1}])

    with pytest.raises(TransfersValidationError):
        await api.enqueue(username="alice", files=[])

    with pytest.raises(TransfersValidationError):
        await api.enqueue(username="alice", files=["not-a-mapping"])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_enqueue_maps_validation_errors() -> None:
    class _ErrorClient(_StubSoulseekClient):
        async def enqueue(
            self, username: str, files: list[dict[str, object]]
        ) -> dict[str, object]:  # type: ignore[override]
            raise SoulseekClientError("bad request", status_code=400)

    api = TransfersApi(_ErrorClient())

    with pytest.raises(TransfersValidationError) as exc:
        await api.enqueue(username="alice", files=[{"download_id": 100}])

    assert exc.value.code.value == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_enqueue_maps_dependency_errors() -> None:
    class _ErrorClient(_StubSoulseekClient):
        async def enqueue(
            self, username: str, files: list[dict[str, object]]
        ) -> dict[str, object]:  # type: ignore[override]
            raise SoulseekClientError("timeout", status_code=503)

    api = TransfersApi(_ErrorClient())

    with pytest.raises(TransfersDependencyError):
        await api.enqueue(username="alice", files=[{"download_id": 101}])
