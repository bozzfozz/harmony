"""Wrapper around the slskd transfers endpoints."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core.soulseek_client import SoulseekClient, SoulseekClientError
from app.errors import ErrorCode


class TransfersApiError(RuntimeError):
    """Raised when the slskd transfers API cannot fulfil a request."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.DEPENDENCY_ERROR,
        status_code: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = dict(details) if details is not None else None


class TransfersDependencyError(TransfersApiError):
    """Raised when slskd is unavailable or returned a 5xx error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.DEPENDENCY_ERROR,
            status_code=status_code,
            details=details,
        )


class TransfersNotFoundError(TransfersApiError):
    """Raised when a download transfer could not be located."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.NOT_FOUND,
            status_code=status_code,
            details=details,
        )


class TransfersValidationError(TransfersApiError):
    """Raised when invalid data is provided to the transfers API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=status_code,
            details=details,
        )


class TransfersApi:
    """Provide a small abstraction for download transfer operations."""

    def __init__(self, client: SoulseekClient) -> None:
        self._client = client

    async def cancel_download(self, transfer_id: str | int) -> bool:
        """Cancel a download via slskd."""

        normalised = self._normalise_transfer_id(transfer_id)
        try:
            payload = await self._client.cancel_download(normalised)
        except SoulseekClientError as exc:  # pragma: no cover - network failure path
            self._raise_from_client_error("Failed to cancel download", exc)
        return self._acknowledged(payload)

    async def enqueue(
        self,
        *,
        username: str,
        files: Iterable[Mapping[str, Any]],
    ) -> str:
        """Enqueue a new download job for the given user and files."""

        normalised_username = username.strip()
        if not normalised_username:
            raise TransfersValidationError("username must not be empty")
        normalised_files = self._normalise_files(files)

        try:
            payload = await self._client.enqueue(normalised_username, normalised_files)
        except SoulseekClientError as exc:  # pragma: no cover - network failure path
            self._raise_from_client_error("Failed to enqueue download", exc)

        return self._extract_identifier(payload, normalised_files, normalised_username)

    @staticmethod
    def _normalise_transfer_id(transfer_id: str | int) -> str:
        if isinstance(transfer_id, str):
            candidate = transfer_id.strip()
            if not candidate:
                raise TransfersValidationError("transfer_id must not be empty")
            return candidate
        if isinstance(transfer_id, int):
            if transfer_id <= 0:
                raise TransfersValidationError("transfer_id must be positive")
            return str(transfer_id)
        raise TransfersValidationError("transfer_id must be a string or integer")

    @staticmethod
    def _normalise_files(files: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index, file_entry in enumerate(files, start=1):
            if not isinstance(file_entry, Mapping):
                raise TransfersValidationError(
                    f"files[{index - 1}] must be a mapping, got {type(file_entry)!r}",
                )
            normalised = dict(file_entry)
            filename = normalised.get("filename") or normalised.get("name")
            if filename:
                normalised["filename"] = str(filename)
            result.append(normalised)

        if not result:
            raise TransfersValidationError("files must contain at least one entry")
        return result

    @staticmethod
    def _extract_identifier(
        payload: Any,
        files: Sequence[Mapping[str, Any]],
        username: str,
    ) -> str:
        if isinstance(payload, Mapping):
            for key in ("job_id", "download_id", "id", "identifier"):
                value = payload.get(key)
                if value:
                    return str(value)
            job = payload.get("job")
            if isinstance(job, Mapping):
                for key in ("id", "download_id", "identifier"):
                    value = job.get(key)
                    if value:
                        return str(value)
            downloads = payload.get("downloads")
            if isinstance(downloads, Sequence):
                for entry in downloads:
                    if isinstance(entry, Mapping):
                        for key in ("id", "download_id", "identifier"):
                            value = entry.get(key)
                            if value:
                                return str(value)

        for file_entry in files:
            value = file_entry.get("download_id") or file_entry.get("id")
            if value:
                return str(value)
            filename = file_entry.get("filename") or file_entry.get("name")
            if filename:
                return str(filename)

        return username

    @staticmethod
    def _acknowledged(payload: Any) -> bool:
        if isinstance(payload, Mapping):
            status = payload.get("status")
            if isinstance(status, str):
                return status.lower() not in {"failed", "error"}
            if isinstance(status, bool):
                return status
            cancelled = payload.get("cancelled")
            if cancelled:
                return True
        return True

    @staticmethod
    def _raise_from_client_error(message: str, exc: SoulseekClientError) -> None:
        status_code = getattr(exc, "status_code", None)
        details = exc.payload if isinstance(exc.payload, Mapping) else None
        if status_code == 404:
            raise TransfersNotFoundError(
                message, status_code=status_code, details=details
            ) from exc
        if status_code in {400, 422}:
            raise TransfersValidationError(
                message, status_code=status_code, details=details
            ) from exc
        raise TransfersDependencyError(
            message, status_code=status_code, details=details
        ) from exc
