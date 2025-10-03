"""Service layer for download-related database and worker interactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from fastapi import status
from sqlalchemy.orm import Session

from app.core.transfers_api import TransfersApi, TransfersApiError
from app.errors import (
    AppError,
    DependencyError,
    ErrorCode,
    InternalServerError,
    NotFoundError,
    ValidationAppError,
)
from app.logging import get_logger
from app.models import Download
from app.db import SessionCallable
from app.schemas import DownloadPriorityUpdate, SoulseekDownloadRequest
from app.schemas.errors import ApiError
from app.services.errors import to_api_error
from app.utils.activity import record_activity
from app.utils.downloads import (
    ACTIVE_STATES,
    coerce_priority,
    determine_priority,
    render_downloads_csv,
    resolve_status_filter,
    serialise_download,
)
from app.utils.events import DOWNLOAD_BLOCKED
from app.utils.service_health import collect_missing_credentials
from app.workers.persistence import update_priority as update_worker_priority


logger = get_logger(__name__)


_ERROR_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: status.HTTP_400_BAD_REQUEST,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.DEPENDENCY_ERROR: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def _app_error_from_api_error(api_error: ApiError) -> AppError:
    code = ErrorCode(api_error.error.code)
    status_code = _ERROR_STATUS_BY_CODE.get(code, status.HTTP_500_INTERNAL_SERVER_ERROR)
    return AppError(
        api_error.error.message,
        code=code,
        http_status=status_code,
        meta=api_error.error.details,
    )


@dataclass
class DownloadSummary:
    id: int
    filename: str
    state: str
    progress: float
    priority: int
    username: Optional[str]
    request_payload: Optional[Dict[str, Any]] = None


@dataclass
class QueueDownloadsResult:
    downloads: List[DownloadSummary]
    job_files: List[Dict[str, Any]]
    job_priority: int


@dataclass
class RetryPreparation:
    original: DownloadSummary
    filename: str
    payload: Dict[str, Any]
    priority: int


@dataclass
class RetryPersistenceResult:
    download: DownloadSummary
    payload: Dict[str, Any]
    filename: str
    username: Optional[str]


SessionRunner = Callable[[SessionCallable[Any]], Awaitable[Any]]


class DownloadService:
    """Encapsulates persistence and worker coordination for downloads."""

    def __init__(
        self,
        *,
        session: Session,
        session_runner: SessionRunner,
        transfers: TransfersApi,
    ) -> None:
        self._session = session
        self._run_session = session_runner
        self._transfers = transfers

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def _build_download_query(
        self,
        *,
        include_all: bool,
        status_filter: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
    ) -> Any:
        query = self._session.query(Download)
        if status_filter:
            states = resolve_status_filter(status_filter)
            query = query.filter(Download.state.in_(tuple(states)))
        elif not include_all:
            query = query.filter(Download.state.in_(tuple(ACTIVE_STATES)))

        if created_from:
            query = query.filter(Download.created_at >= created_from)
        if created_to:
            query = query.filter(Download.created_at <= created_to)

        return query.order_by(Download.priority.desc(), Download.created_at.desc())

    def list_downloads(
        self,
        *,
        include_all: bool,
        status_filter: Optional[str],
        limit: int,
        offset: int,
    ) -> List[Download]:
        try:
            query = self._build_download_query(
                include_all=include_all, status_filter=status_filter
            )
            return query.offset(offset).limit(limit).all()
        except AppError:
            raise
        except Exception as exc:  # pragma: no cover - defensive database failure handling
            logger.exception("Failed to list downloads: %s", exc)
            raise InternalServerError("Failed to fetch downloads") from exc

    def get_download(self, download_id: int) -> Download:
        try:
            download = self._session.get(Download, download_id)
        except AppError:
            raise
        except Exception as exc:  # pragma: no cover - defensive database failure handling
            logger.exception("Failed to load download %s: %s", download_id, exc)
            raise InternalServerError("Failed to fetch download") from exc

        if download is None:
            logger.warning("Download %s not found", download_id)
            raise NotFoundError("Download not found")
        return download

    def update_priority(self, download_id: int, payload: DownloadPriorityUpdate) -> Download:
        download = self.get_download(download_id)

        new_priority = int(payload.priority)
        download.priority = new_priority
        download.updated_at = datetime.utcnow()
        payload_copy = dict(download.request_payload or {})
        payload_copy["priority"] = new_priority
        download.request_payload = payload_copy

        self._session.add(download)
        self._session.commit()

        logger.info("Updated priority for download %s to %s", download_id, new_priority)

        job_id = download.job_id
        if job_id and not update_worker_priority(job_id, new_priority, job_type="sync"):
            logger.error(
                "Failed to update worker job priority for download %s (job %s)",
                download_id,
                job_id,
            )

        return download

    async def queue_downloads(
        self,
        payload: SoulseekDownloadRequest,
        *,
        worker: Any,
    ) -> Dict[str, Any]:
        if not payload.files:
            logger.warning("Download request without files rejected")
            raise ValidationAppError("No files supplied")

        missing_credentials = await self._run_session(
            lambda session: collect_missing_credentials(session, ("soulseek",))
        )
        if missing_credentials:
            missing_payload = {
                service: list(values) for service, values in missing_credentials.items()
            }
            logger.warning("Download blocked due to missing credentials: %s", missing_payload)
            record_activity(
                "download",
                DOWNLOAD_BLOCKED,
                details={"missing": missing_payload, "username": payload.username},
            )
            raise DependencyError("Download blocked", meta={"missing": missing_payload})

        enqueue = getattr(worker, "enqueue", None) if worker else None
        if enqueue is None:
            logger.error("Download worker unavailable for request from %s", payload.username)
            record_activity("download", "failed", details={"reason": "worker_unavailable"})
            raise DependencyError("Download worker unavailable")

        try:
            result = await self._run_session(
                lambda session: _queue_downloads_with_session(session, payload)
            )
        except Exception as exc:  # pragma: no cover - defensive persistence handling
            logger.exception("Failed to persist download request: %s", exc)
            record_activity("download", "failed", details={"reason": "persistence_error"})
            raise InternalServerError("Failed to queue download") from exc

        job = {
            "username": payload.username,
            "files": result.job_files,
            "priority": result.job_priority,
        }
        try:
            await enqueue(job)  # type: ignore[func-returns-value]
        except Exception as exc:  # pragma: no cover - defensive worker error
            logger.exception("Failed to enqueue download job: %s", exc)
            await self._run_session(
                lambda session: _mark_downloads_failed(session, [d.id for d in result.downloads])
            )
            record_activity("download", "failed", details={"reason": "enqueue_error"})
            raise DependencyError("Failed to enqueue download") from exc

        record_activity(
            "download",
            "queued",
            details={
                "download_ids": [download.id for download in result.downloads],
                "username": payload.username,
            },
        )

        logger.info("Queued %d download(s) for %s", len(result.downloads), payload.username)

        download_payload = [
            {
                "id": download.id,
                "filename": download.filename,
                "state": download.state,
                "progress": download.progress,
                "priority": download.priority,
                "username": download.username,
            }
            for download in result.downloads
        ]

        response: Dict[str, Any] = {"status": "queued", "downloads": download_payload}
        if result.downloads:
            response["download_id"] = result.downloads[0].id
        return response

    async def cancel_download(self, download_id: int) -> Dict[str, Any]:
        download = await self._run_session(
            lambda session: _get_download_summary(session, download_id)
        )

        if download.state not in {"queued", "running", "downloading"}:
            logger.warning(
                "Cancellation rejected for download %s due to invalid state %s",
                download_id,
                download.state,
            )
            raise AppError(
                "Download cannot be cancelled in its current state",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=status.HTTP_409_CONFLICT,
            )

        try:
            await self._transfers.cancel_download(download_id)
        except TransfersApiError as exc:
            logger.error("slskd cancellation failed for %s: %s", download_id, exc)
            api_error = to_api_error(exc, provider="slskd")
            raise _app_error_from_api_error(api_error) from exc

        try:
            await self._run_session(lambda session: _mark_download_cancelled(session, download_id))
        except Exception as exc:  # pragma: no cover - defensive persistence handling
            logger.exception("Failed to persist cancellation for download %s: %s", download_id, exc)
            raise InternalServerError("Failed to cancel download") from exc

        record_activity(
            "download",
            "download_cancelled",
            details={"download_id": download_id, "filename": download.filename},
        )

        return {"status": "cancelled", "download_id": download_id}

    def export_downloads(
        self,
        *,
        status_filter: Optional[str],
        created_from: Optional[datetime],
        created_to: Optional[datetime],
        format: str,
    ) -> ResponsePayload:
        try:
            query = self._build_download_query(
                include_all=True,
                status_filter=status_filter,
                created_from=created_from,
                created_to=created_to,
            )
            downloads = query.all()
        except AppError:
            raise
        except Exception as exc:  # pragma: no cover - defensive database failure handling
            logger.exception("Failed to export downloads: %s", exc)
            raise InternalServerError("Failed to export downloads") from exc

        payload = [serialise_download(item) for item in downloads]
        if format == "csv":
            return {"content": render_downloads_csv(payload), "media_type": "text/csv"}
        return {
            "content": payload,
            "media_type": "application/json",
        }

    async def retry_download(self, download_id: int) -> Dict[str, Any]:
        original = await self._run_session(
            lambda session: _prepare_retry(session, download_id)
        )

        try:
            await self._transfers.cancel_download(download_id)
        except TransfersApiError as exc:
            logger.error("slskd cancellation before retry failed for %s: %s", download_id, exc)
            api_error = to_api_error(exc, provider="slskd")
            raise _app_error_from_api_error(api_error) from exc

        try:
            persistence = await self._run_session(
                lambda session: _create_retry_download(session, original)
            )
        except Exception as exc:  # pragma: no cover - defensive persistence handling
            logger.exception("Failed to persist retry download for %s: %s", download_id, exc)
            raise InternalServerError("Failed to retry download") from exc

        try:
            await self._transfers.enqueue(
                username=persistence.username or "", files=[persistence.payload]
            )
        except TransfersApiError as exc:
            try:
                await self._run_session(
                    lambda session: _delete_download(session, persistence.download.id)
                )
            except Exception as cleanup_exc:  # pragma: no cover - defensive cleanup
                logger.exception(
                    "Failed to remove retry download %s after enqueue error: %s",
                    persistence.download.id,
                    cleanup_exc,
                )
            logger.error("Failed to enqueue retry for download %s: %s", download_id, exc)
            api_error = to_api_error(exc, provider="slskd")
            raise _app_error_from_api_error(api_error) from exc
        except Exception as exc:  # pragma: no cover - defensive unexpected failure
            try:
                await self._run_session(
                    lambda session: _delete_download(session, persistence.download.id)
                )
            except Exception as cleanup_exc:  # pragma: no cover - defensive cleanup
                logger.exception(
                    "Failed to remove retry download %s after unexpected error: %s",
                    persistence.download.id,
                    cleanup_exc,
                )
            logger.exception("Unexpected error while retrying download %s: %s", download_id, exc)
            raise InternalServerError("Failed to retry download") from exc

        record_activity(
            "download",
            "download_retried",
            details={
                "original_download_id": download_id,
                "retry_download_id": persistence.download.id,
                "username": persistence.username,
                "filename": persistence.filename,
            },
        )

        return {"status": "queued", "download_id": persistence.download.id}


ResponsePayload = Dict[str, Any]


def _queue_downloads_with_session(
    session: Session, payload: SoulseekDownloadRequest
) -> QueueDownloadsResult:
    download_summaries: List[DownloadSummary] = []
    job_files: List[Dict[str, Any]] = []
    job_priorities: List[int] = []

    try:
        for file_info in payload.files:
            file_payload = file_info.to_payload()
            filename = str(file_payload.get("filename") or "unknown")
            priority = determine_priority(file_payload)
            download = Download(
                filename=filename,
                state="queued",
                progress=0.0,
                username=payload.username,
                priority=priority,
            )
            session.add(download)
            session.flush()

            payload_copy = dict(file_payload)
            payload_copy["download_id"] = download.id
            payload_copy["priority"] = priority
            download.request_payload = payload_copy
            job_files.append(payload_copy)
            job_priorities.append(priority)

            download_summaries.append(
                DownloadSummary(
                    id=download.id,
                    filename=download.filename,
                    state=download.state,
                    progress=download.progress,
                    priority=download.priority,
                    username=download.username,
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    job_priority = max(job_priorities or [0])
    return QueueDownloadsResult(
        downloads=download_summaries,
        job_files=job_files,
        job_priority=job_priority,
    )


def _mark_downloads_failed(session: Session, download_ids: Sequence[int]) -> None:
    if not download_ids:
        return

    try:
        downloads = (
            session.query(Download).filter(Download.id.in_(tuple(download_ids))).all()
        )
        now = datetime.utcnow()
        for download in downloads:
            download.state = "failed"
            download.updated_at = now
        session.commit()
    except Exception:
        session.rollback()
        raise


def _get_download_summary(session: Session, download_id: int) -> DownloadSummary:
    download = session.get(Download, download_id)
    if download is None:
        logger.warning("Download %s not found", download_id)
        raise NotFoundError("Download not found")

    request_payload = dict(download.request_payload or {}) if download.request_payload else None
    return DownloadSummary(
        id=download.id,
        filename=download.filename,
        state=download.state,
        progress=download.progress,
        priority=download.priority,
        username=download.username,
        request_payload=request_payload,
    )


def _mark_download_cancelled(session: Session, download_id: int) -> None:
    download = session.get(Download, download_id)
    if download is None:
        logger.warning("Download %s not found for cancellation", download_id)
        raise NotFoundError("Download not found")

    try:
        download.state = "cancelled"
        download.updated_at = datetime.utcnow()
        session.commit()
    except Exception:
        session.rollback()
        raise


def _prepare_retry(session: Session, download_id: int) -> RetryPreparation:
    download = _get_download_summary(session, download_id)

    if download.state not in {"failed", "cancelled"}:
        logger.warning(
            "Retry rejected for download %s due to invalid state %s",
            download_id,
            download.state,
        )
        raise AppError(
            "Download cannot be retried in its current state",
            code=ErrorCode.VALIDATION_ERROR,
            http_status=status.HTTP_409_CONFLICT,
        )

    if not download.username or not download.request_payload:
        logger.error("Retry rejected for download %s due to missing payload", download_id)
        raise ValidationAppError(
            "Download cannot be retried because original request data is missing"
        )

    payload_copy = dict(download.request_payload)
    filename = payload_copy.get("filename") or download.filename
    if not filename:
        logger.error("Retry rejected for download %s due to missing filename", download_id)
        raise ValidationAppError(
            "Download cannot be retried because filename is unknown"
        )

    filesize = (
        payload_copy.get("filesize")
        or payload_copy.get("size")
        or payload_copy.get("file_size")
    )
    if filesize is not None:
        payload_copy.setdefault("filesize", filesize)

    priority = coerce_priority(payload_copy.get("priority"))
    if priority is None:
        priority = download.priority

    payload_copy.setdefault("filename", filename)
    payload_copy["priority"] = priority

    return RetryPreparation(
        original=download,
        filename=filename,
        payload=payload_copy,
        priority=priority,
    )


def _create_retry_download(
    session: Session, preparation: RetryPreparation
) -> RetryPersistenceResult:
    download = Download(
        filename=preparation.filename,
        state="queued",
        progress=0.0,
        username=preparation.original.username,
        priority=preparation.priority,
    )
    try:
        session.add(download)
        session.flush()

        payload_copy = dict(preparation.payload)
        payload_copy["download_id"] = download.id
        payload_copy.setdefault("filename", preparation.filename)
        payload_copy["priority"] = preparation.priority
        download.request_payload = payload_copy
        session.commit()
    except Exception:
        session.rollback()
        raise

    summary = DownloadSummary(
        id=download.id,
        filename=download.filename,
        state=download.state,
        progress=download.progress,
        priority=download.priority,
        username=download.username,
        request_payload=dict(download.request_payload or {}),
    )
    return RetryPersistenceResult(
        download=summary,
        payload=payload_copy,
        filename=preparation.filename,
        username=preparation.original.username,
    )


def _delete_download(session: Session, download_id: int) -> None:
    download = session.get(Download, download_id)
    if download is None:
        return

    try:
        session.delete(download)
        session.commit()
    except Exception:
        session.rollback()
        raise
