"""Async HTTP client for the slskd API used by the Harmony Download Manager."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping

import httpx

from app.utils.retry import RetryDirective, with_retry


class SlskdClientError(RuntimeError):
    """Base exception raised for slskd client failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class SlskdTimeoutError(SlskdClientError):
    """Raised when a request exceeded the configured timeout."""

    def __init__(self, message: str = "slskd request timed out") -> None:
        super().__init__(message, retryable=True)


class SlskdInvalidResponseError(SlskdClientError):
    """Raised when the upstream payload cannot be decoded as JSON."""


class SlskdHTTPStatusError(SlskdClientError):
    """Raised when the upstream service returned an unexpected status code."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, retryable=retryable)
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.body = body


class SlskdRateLimitedError(SlskdHTTPStatusError):
    """Raised when slskd rejected the request due to rate limits."""

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(
            429,
            "slskd rate limited the request",
            headers=headers,
            retryable=True,
        )
        self.retry_after_ms = retry_after_ms


class SlskdDownloadStatus(str, Enum):
    """Normalised download lifecycle states reported by slskd."""

    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class SlskdDownloadEvent:
    """Represents a status update emitted by slskd for a download."""

    download_id: str
    status: SlskdDownloadStatus
    payload: Mapping[str, Any]
    retryable: bool
    path: str | None = None
    bytes_written: int | None = None


@dataclass(slots=True)
class SlskdHttpClient:
    """HTTPX based client tailored to the Harmony Download Manager (HDM)."""

    base_url: str
    api_key: str | None = None
    transport: httpx.AsyncBaseTransport | None = None
    timeout_ms: int = 8_000
    max_attempts: int = 3
    backoff_base_ms: int = 250
    jitter_pct: int = 20
    status_poll_interval: float = 1.0

    async def search_tracks(self, query: str, *, limit: int, timeout_ms: int) -> Any:
        """Issue a search request against slskd and return the JSON payload."""

        response = await self._request(
            "GET",
            "/api/v0/search/tracks",
            params={"query": query, "limit": limit},
            timeout_ms=timeout_ms,
        )
        return self._decode_json(response)

    async def enqueue_download(
        self,
        username: str,
        files: list[Mapping[str, Any]],
        *,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        payload = {"username": username, "files": files}
        response = await self._request(
            "POST",
            "/api/v0/transfers/enqueue",
            json=payload,
            idempotency_key=idempotency_key,
        )
        return self._decode_json(response)

    async def stream_download_events(
        self,
        idempotency_key: str,
        *,
        poll_interval: float | None = None,
    ) -> AsyncIterator[SlskdDownloadEvent]:
        """Yield status events for the download identified by *idempotency_key*."""

        interval = (
            poll_interval if poll_interval is not None else self.status_poll_interval
        )
        interval = max(0.25, float(interval))
        last_status: SlskdDownloadStatus | None = None
        while True:
            response = await self._request(
                "GET",
                f"/api/v0/transfers/downloads/{idempotency_key}",
                idempotency_key=idempotency_key,
            )
            payload = self._decode_json(response)
            event = self._parse_event(payload, fallback_id=idempotency_key)
            if last_status != event.status:
                yield event
                last_status = event.status
            if event.status in {
                SlskdDownloadStatus.COMPLETED,
                SlskdDownloadStatus.FAILED,
            }:
                return
            await asyncio.sleep(interval)

    async def forward_completion_events(
        self,
        idempotency_key: str,
        *,
        publish: Callable[[str, Path, int], Awaitable[None]],
        poll_interval: float | None = None,
    ) -> None:
        """Stream completion updates and publish them to the completion monitor."""

        async for event in self.stream_download_events(
            idempotency_key, poll_interval=poll_interval
        ):
            if event.status is SlskdDownloadStatus.COMPLETED and event.path:
                await publish(
                    event.download_id,
                    Path(event.path),
                    int(event.bytes_written or 0),
                )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> httpx.Response:
        base_url = self.base_url.rstrip("/")
        timeout = self._build_timeout(timeout_ms or self.timeout_ms)

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        async def _perform_request() -> httpx.Response:
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=timeout,
                    headers=headers,
                    transport=self.transport,
                ) as client:
                    response = await client.request(
                        method,
                        path,
                        params=params,
                        json=json,
                    )
            except httpx.TimeoutException as exc:
                raise SlskdTimeoutError() from exc
            except httpx.HTTPError as exc:
                raise SlskdClientError(
                    f"slskd request failed: {exc}", retryable=True
                ) from exc

            if response.status_code == httpx.codes.OK:
                return response
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                retry_after = _parse_retry_after_ms(response.headers)
                raise SlskdRateLimitedError(
                    headers=response.headers, retry_after_ms=retry_after
                )

            body_preview = response.text[:200]
            if 500 <= response.status_code < 600:
                raise SlskdHTTPStatusError(
                    response.status_code,
                    "slskd returned a server error",
                    headers=response.headers,
                    body=body_preview,
                    retryable=True,
                )
            if 400 <= response.status_code < 500:
                raise SlskdHTTPStatusError(
                    response.status_code,
                    "slskd rejected the request",
                    headers=response.headers,
                    body=body_preview,
                    retryable=False,
                )
            raise SlskdHTTPStatusError(
                response.status_code,
                "slskd responded with an unexpected status",
                headers=response.headers,
                body=body_preview,
                retryable=True,
            )

        def _classify(error: Exception) -> RetryDirective:
            if isinstance(error, SlskdRateLimitedError):
                return RetryDirective(
                    retry=True,
                    delay_override_ms=error.retry_after_ms,
                    error=error,
                )
            if isinstance(error, SlskdClientError):
                return RetryDirective(retry=error.retryable, error=error)
            return RetryDirective(retry=False, error=error)

        return await with_retry(
            _perform_request,
            attempts=max(1, int(self.max_attempts)),
            base_ms=max(1, int(self.backoff_base_ms)),
            jitter_pct=max(0, int(self.jitter_pct)),
            timeout_ms=timeout_ms or self.timeout_ms,
            classify_err=_classify,
        )

    def _parse_event(
        self, payload: Mapping[str, Any] | Any, *, fallback_id: str
    ) -> SlskdDownloadEvent:
        if not isinstance(payload, Mapping):
            raise SlskdInvalidResponseError("slskd returned unexpected payload")

        raw_status = str(payload.get("status") or payload.get("state") or "").strip()
        status = _normalise_status(raw_status)
        download_id = str(
            payload.get("download_id")
            or payload.get("id")
            or payload.get("job_id")
            or fallback_id
        )

        retryable = bool(payload.get("retryable", False))
        error_code = str(payload.get("error_code") or "").upper()
        if error_code in {"TIMEOUT", "SERVER_ERROR", "RATE_LIMIT"}:
            retryable = True

        path = _extract_path(payload)
        bytes_written = _extract_bytes(payload)

        return SlskdDownloadEvent(
            download_id=download_id,
            status=status,
            payload=payload,
            retryable=retryable,
            path=path,
            bytes_written=bytes_written,
        )

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise SlskdInvalidResponseError("slskd returned invalid JSON") from exc

    @staticmethod
    def _build_timeout(timeout_ms: int) -> httpx.Timeout:
        timeout_seconds = max(timeout_ms, 100) / 1000
        connect_timeout = min(timeout_seconds, 5.0)
        return httpx.Timeout(
            timeout_seconds,
            connect=connect_timeout,
            read=timeout_seconds,
            write=timeout_seconds,
        )


def _extract_path(payload: Mapping[str, Any]) -> str | None:
    for key in ("path", "file_path", "local_path", "source_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_bytes(payload: Mapping[str, Any]) -> int | None:
    for key in ("bytes", "bytes_written", "size_bytes"):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            try:
                return int(value)
            except ValueError:  # pragma: no cover - defensive guard
                continue
    return None


def _normalise_status(raw: str) -> SlskdDownloadStatus:
    normalised = raw.lower().replace(" ", "_")
    if normalised in {"accepted", "queued", "pending"}:
        return SlskdDownloadStatus.ACCEPTED
    if normalised in {"in_progress", "downloading", "running", "transferring"}:
        return SlskdDownloadStatus.IN_PROGRESS
    if normalised in {"completed", "done", "success", "succeeded"}:
        return SlskdDownloadStatus.COMPLETED
    if normalised in {"failed", "error", "cancelled", "canceled"}:
        return SlskdDownloadStatus.FAILED
    # default to in-progress to avoid premature termination
    return SlskdDownloadStatus.IN_PROGRESS


def _parse_retry_after_ms(headers: Mapping[str, Any]) -> int | None:
    value = headers.get("Retry-After") if isinstance(headers, Mapping) else None
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value * 1000))
    try:
        numeric = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(0, numeric * 1000)


__all__ = [
    "SlskdClientError",
    "SlskdDownloadEvent",
    "SlskdDownloadStatus",
    "SlskdHttpClient",
    "SlskdHTTPStatusError",
    "SlskdInvalidResponseError",
    "SlskdRateLimitedError",
    "SlskdTimeoutError",
]
