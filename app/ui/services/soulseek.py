"""Soulseek UI service exposing integration status and configuration."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request

from app.config import AppConfig, SecurityConfig, SoulseekConfig
from app.core.soulseek_client import SoulseekClient
from app.dependencies import (
    get_app_config,
    get_provider_registry,
    get_soulseek_client,
)
from app.integrations.health import IntegrationHealth, ProviderHealthMonitor
from app.integrations.registry import ProviderRegistry
from app.logging import get_logger
from app.routers.soulseek_router import (
    soulseek_all_uploads,
    soulseek_cancel_upload,
    soulseek_status,
    soulseek_uploads,
    soulseek_user_address,
    soulseek_user_browse,
    soulseek_user_directory,
    soulseek_user_info,
)
from app.schemas import StatusResponse
from app.ui.context import SuggestedTask, _normalise_status

logger = get_logger(__name__)


@dataclass(slots=True)
class SoulseekUploadRow:
    """Lightweight representation of an active Soulseek upload."""

    identifier: str
    filename: str
    status: str
    progress: float | None
    size_bytes: int | None
    speed_bps: float | None
    username: str | None


@dataclass(slots=True)
class SoulseekUserProfile:
    """Normalised view of a Soulseek user's profile details."""

    username: str
    address: Mapping[str, str]
    info: Mapping[str, str]


@dataclass(slots=True)
class SoulseekUserStatus:
    """Snapshot of a Soulseek user's availability state."""

    username: str
    state: str
    message: str | None
    shared_files: int | None
    average_speed_bps: float | None


@dataclass(slots=True)
class SoulseekUserBrowsingStatus:
    """Progress record for a Soulseek user directory browse request."""

    username: str
    state: str
    progress: float | None
    queue_position: int | None
    queue_length: int | None
    message: str | None


@dataclass(slots=True)
class SoulseekUserDirectoryEntry:
    """Directory entry available for browsing."""

    name: str
    path: str


@dataclass(slots=True)
class SoulseekUserFileEntry:
    """File entry within a Soulseek user's shared directory."""

    name: str
    path: str | None
    size_bytes: int | None


@dataclass(slots=True)
class SoulseekUserDirectoryListing:
    """Directory listing for a Soulseek user."""

    username: str
    current_path: str | None
    parent_path: str | None
    directories: tuple[SoulseekUserDirectoryEntry, ...]
    files: tuple[SoulseekUserFileEntry, ...]


_HEALTHY_STATUSES: frozenset[str] = frozenset({"ok", "connected", "online"})


class SoulseekUiService:
    """Service aggregating Soulseek integration metadata for the UI layer."""

    def __init__(
        self,
        *,
        request: Request,
        config: AppConfig,
        soulseek_client: SoulseekClient,
        registry: ProviderRegistry,
    ) -> None:
        self._request = request
        self._config = config
        self._client = soulseek_client
        self._registry = registry
        self._registry.initialise()
        self._health_monitor = ProviderHealthMonitor(self._registry)

    async def status(self) -> StatusResponse:
        """Return the Soulseek daemon connectivity status."""

        return await soulseek_status(client=self._client)

    async def integration_health(self) -> IntegrationHealth:
        """Return integration health reports for configured providers."""

        return await self._health_monitor.check_all()

    def soulseek_config(self) -> SoulseekConfig:
        """Expose the configured Soulseek settings."""

        return self._config.soulseek

    def security_config(self) -> SecurityConfig:
        """Expose the security profile for UI rendering."""

        return self._config.security

    async def uploads(self, *, include_all: bool = False) -> Sequence[SoulseekUploadRow]:
        """Return normalised upload rows for the requested scope."""

        if include_all:
            payload = await soulseek_all_uploads(client=self._client)
        else:
            payload = await soulseek_uploads(client=self._client)
        uploads_raw = self._extract_uploads(payload)
        rows: list[SoulseekUploadRow] = []
        for entry in uploads_raw:
            row = self._to_row(entry)
            if row is not None:
                rows.append(row)
        logger.debug(
            "soulseek.ui.uploads",  # structured logging for observability
            extra={
                "include_all": include_all,
                "count": len(rows),
            },
        )
        return tuple(rows)

    async def cancel_upload(self, *, upload_id: str) -> None:
        """Cancel an upload through the Soulseek router."""

        if not upload_id:
            raise ValueError("upload_id is required")
        await soulseek_cancel_upload(upload_id=upload_id, client=self._client)
        logger.info(
            "soulseek.ui.upload.cancelled",
            extra={"upload_id": upload_id},
        )

    async def user_profile(self, *, username: str) -> SoulseekUserProfile:
        """Fetch combined Soulseek user profile information."""

        trimmed = (username or "").strip()
        if not trimmed:
            raise ValueError("username is required")

        address_raw = await soulseek_user_address(username=trimmed, client=self._client)
        info_raw = await soulseek_user_info(username=trimmed, client=self._client)

        profile = SoulseekUserProfile(
            username=trimmed,
            address=self._normalise_mapping(address_raw),
            info=self._normalise_mapping(info_raw),
        )
        logger.debug(
            "soulseek.ui.user.profile",
            extra={
                "username": trimmed,
                "address_keys": sorted(profile.address.keys()),
                "info_keys": sorted(profile.info.keys()),
            },
        )
        return profile

    async def user_status(self, *, username: str) -> SoulseekUserStatus:
        """Return the availability status for a Soulseek user."""

        trimmed = (username or "").strip()
        if not trimmed:
            raise ValueError("username is required")

        payload = await soulseek_user_status(username=trimmed, client=self._client)
        mapping = payload if isinstance(payload, Mapping) else {}
        state_raw = mapping.get("status") or mapping.get("state") or "unknown"
        state = _normalise_status(str(state_raw)) if state_raw is not None else "unknown"
        message_raw = (
            mapping.get("message") or mapping.get("status_message") or mapping.get("detail")
        )
        message = str(message_raw).strip() if isinstance(message_raw, str) else None
        if message == "":
            message = None
        shared_files = self._coerce_int(
            mapping.get("shared_files")
            or mapping.get("shared")
            or mapping.get("shared_count")
            or mapping.get("files")
        )
        average_speed = self._coerce_float(
            mapping.get("average_speed") or mapping.get("avg_speed") or mapping.get("speed")
        )
        status = SoulseekUserStatus(
            username=trimmed,
            state=state or "unknown",
            message=message,
            shared_files=shared_files,
            average_speed_bps=average_speed,
        )
        logger.debug(
            "soulseek.ui.user.status",
            extra={
                "username": trimmed,
                "state": status.state,
                "shared_files": status.shared_files,
                "average_speed_bps": status.average_speed_bps,
            },
        )
        return status

    async def user_browsing_status(
        self,
        *,
        username: str,
    ) -> SoulseekUserBrowsingStatus:
        """Return the browse progress for a Soulseek user."""

        trimmed = (username or "").strip()
        if not trimmed:
            raise ValueError("username is required")

        payload = await soulseek_user_browsing_status(username=trimmed, client=self._client)
        mapping = payload if isinstance(payload, Mapping) else {}
        state_raw = mapping.get("status") or mapping.get("state") or "unknown"
        state = _normalise_status(str(state_raw)) if state_raw is not None else "unknown"
        message_raw = (
            mapping.get("message") or mapping.get("status_message") or mapping.get("detail")
        )
        message = str(message_raw).strip() if isinstance(message_raw, str) else None
        if message == "":
            message = None
        progress = self._coerce_progress(mapping.get("progress") or mapping.get("percent"))
        queue_position = self._coerce_int(mapping.get("queue_position") or mapping.get("position"))
        queue_length = self._coerce_int(
            mapping.get("queue_length") or mapping.get("queue_size") or mapping.get("total")
        )
        status = SoulseekUserBrowsingStatus(
            username=trimmed,
            state=state or "unknown",
            progress=progress,
            queue_position=queue_position,
            queue_length=queue_length,
            message=message,
        )
        logger.debug(
            "soulseek.ui.user.browsing_status",
            extra={
                "username": trimmed,
                "state": status.state,
                "progress": status.progress,
                "queue_position": status.queue_position,
                "queue_length": status.queue_length,
            },
        )
        return status

    async def user_directory(
        self,
        *,
        username: str,
        path: str | None = None,
    ) -> SoulseekUserDirectoryListing:
        """Browse a Soulseek user's shared directories."""

        trimmed = (username or "").strip()
        if not trimmed:
            raise ValueError("username is required")

        if path:
            payload = await soulseek_user_directory(
                username=trimmed,
                path=path,
                client=self._client,
            )
            current_path = (
                str(payload.get("path") or path).strip() if isinstance(payload, Mapping) else path
            )
        else:
            payload = await soulseek_user_browse(username=trimmed, client=self._client)
            current_path = (
                str(payload.get("path") or "").strip() if isinstance(payload, Mapping) else None
            )

        directories = self._extract_directories(payload)
        files = self._extract_files(payload)
        parent_path = self._derive_parent_path(current_path)

        listing = SoulseekUserDirectoryListing(
            username=trimmed,
            current_path=current_path or None,
            parent_path=parent_path,
            directories=directories,
            files=files,
        )
        logger.debug(
            "soulseek.ui.user.directory",
            extra={
                "username": trimmed,
                "path": listing.current_path or "",
                "directories": len(listing.directories),
                "files": len(listing.files),
            },
        )
        return listing

    def suggested_tasks(
        self,
        *,
        status: StatusResponse,
        health: IntegrationHealth,
        limit: int = 20,
    ) -> Sequence[SuggestedTask]:
        """Return recommended follow-up tasks for the Soulseek integration."""

        if limit <= 0:
            return ()

        config = self._config.soulseek
        security = self._config.security
        normalised_status = _normalise_status(status.status or "")
        daemon_connected = normalised_status in _HEALTHY_STATUSES
        providers_ok = all(
            _normalise_status(report.status or "") in _HEALTHY_STATUSES
            for report in health.providers
        )
        tasks: list[SuggestedTask] = [
            SuggestedTask(
                identifier="daemon",
                title_key="soulseek.task.daemon",
                description_key="soulseek.task.daemon.desc",
                completed=daemon_connected,
            ),
            SuggestedTask(
                identifier="providers",
                title_key="soulseek.task.providers",
                description_key="soulseek.task.providers.desc",
                completed=providers_ok,
            ),
            SuggestedTask(
                identifier="api-key",
                title_key="soulseek.task.api_key",
                description_key="soulseek.task.api_key.desc",
                completed=bool((config.api_key or "").strip()),
            ),
            SuggestedTask(
                identifier="preferred-formats",
                title_key="soulseek.task.formats",
                description_key="soulseek.task.formats.desc",
                completed=bool(config.preferred_formats),
            ),
            SuggestedTask(
                identifier="retry-policy",
                title_key="soulseek.task.retry_policy",
                description_key="soulseek.task.retry_policy.desc",
                completed=config.retry_max >= 3,
            ),
            SuggestedTask(
                identifier="retry-jitter",
                title_key="soulseek.task.retry_jitter",
                description_key="soulseek.task.retry_jitter.desc",
                completed=config.retry_jitter_pct > 0.0,
            ),
            SuggestedTask(
                identifier="timeout",
                title_key="soulseek.task.timeout",
                description_key="soulseek.task.timeout.desc",
                completed=0 < config.timeout_ms <= 10_000,
            ),
            SuggestedTask(
                identifier="max-results",
                title_key="soulseek.task.max_results",
                description_key="soulseek.task.max_results.desc",
                completed=config.max_results <= 100,
            ),
            SuggestedTask(
                identifier="require-auth",
                title_key="soulseek.task.auth",
                description_key="soulseek.task.auth.desc",
                completed=security.require_auth,
            ),
            SuggestedTask(
                identifier="rate-limiting",
                title_key="soulseek.task.rate_limiting",
                description_key="soulseek.task.rate_limiting.desc",
                completed=security.rate_limiting_enabled,
            ),
        ]

        limited = tuple(tasks[: min(len(tasks), limit)])
        logger.debug(
            "soulseek.ui.tasks",
            extra={
                "count": len(limited),
                "completed": sum(1 for task in limited if task.completed),
                "limit": limit,
            },
        )
        return limited

    @staticmethod
    def _extract_uploads(payload: Any) -> Sequence[Any]:
        if isinstance(payload, dict):
            uploads = payload.get("uploads")
            if isinstance(uploads, list):
                return uploads
            if isinstance(uploads, dict):
                return [uploads]
            return []
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _to_row(entry: Any) -> SoulseekUploadRow | None:
        if not isinstance(entry, dict):
            return None
        identifier = str(
            entry.get("id")
            or entry.get("token")
            or entry.get("identifier")
            or entry.get("filename")
            or entry.get("path")
            or "unknown"
        ).strip()
        if not identifier:
            identifier = "unknown"
        progress = SoulseekUiService._coerce_progress(entry.get("progress"))
        size_value = SoulseekUiService._coerce_int(entry.get("size"))
        speed_value = SoulseekUiService._coerce_float(entry.get("speed"))
        username = entry.get("username") or entry.get("user")
        filename = entry.get("filename") or entry.get("path") or entry.get("file") or ""
        status_raw = entry.get("status") or entry.get("state") or "unknown"
        status = str(status_raw) if status_raw is not None else "unknown"
        return SoulseekUploadRow(
            identifier=identifier,
            filename=str(filename),
            status=status,
            progress=progress,
            size_bytes=size_value,
            speed_bps=speed_value,
            username=str(username) if username is not None else None,
        )

    @staticmethod
    def _coerce_progress(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric > 1:
                numeric = numeric / 100.0
            if numeric < 0:
                return 0.0
            if numeric > 1:
                return 1.0
            return numeric
        if isinstance(value, str):
            stripped = value.strip().rstrip("%")
            try:
                numeric = float(stripped)
            except ValueError:
                return None
            if "%" in value or numeric > 1:
                numeric /= 100.0
            numeric = max(0.0, min(numeric, 1.0))
            return numeric
        return None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(float(stripped))
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalise_mapping(payload: Any) -> Mapping[str, str]:
        if not isinstance(payload, Mapping):
            return {}
        normalised: dict[str, str] = {}
        for key, value in payload.items():
            if value in {None, ""}:
                continue
            normalised[str(key)] = str(value)
        return normalised

    @staticmethod
    def _iter_collection(payload: Any, key: str) -> Iterable[Any]:
        if isinstance(payload, Mapping):
            candidate = payload.get(key)
        else:
            candidate = payload
        if candidate is None:
            return ()
        if isinstance(candidate, Mapping):
            return candidate.values()
        if isinstance(candidate, Sequence) and not isinstance(
            candidate, (str, bytes, bytearray)
        ):
            return candidate
        if isinstance(candidate, Iterable) and not isinstance(
            candidate, (str, bytes, bytearray)
        ):
            return candidate
        return ()

    @staticmethod
    def _extract_directories(payload: Any) -> tuple[SoulseekUserDirectoryEntry, ...]:
        entries: list[SoulseekUserDirectoryEntry] = []
        for item in SoulseekUiService._iter_collection(payload, "directories"):
            if not isinstance(item, Mapping):
                continue
            raw_path = item.get("path") or item.get("name") or ""
            path = str(raw_path).strip()
            if not path:
                continue
            name = str(item.get("name") or path.split("/")[-1] or path).strip()
            if not name:
                name = path
            entries.append(SoulseekUserDirectoryEntry(name=name, path=path))
        return tuple(entries)

    @staticmethod
    def _extract_files(payload: Any) -> tuple[SoulseekUserFileEntry, ...]:
        entries: list[SoulseekUserFileEntry] = []
        for item in SoulseekUiService._iter_collection(payload, "files"):
            if not isinstance(item, Mapping):
                continue
            raw_name = (
                item.get("name")
                or item.get("filename")
                or item.get("path")
                or item.get("title")
                or ""
            )
            name = str(raw_name).strip()
            if not name:
                continue
            path_value = item.get("path")
            path = str(path_value).strip() if isinstance(path_value, str) else None
            if "size" in item:
                size_value = item.get("size")
            else:
                size_value = item.get("size_bytes")
            size = SoulseekUiService._coerce_int(size_value)
            entries.append(
                SoulseekUserFileEntry(
                    name=name,
                    path=path,
                    size_bytes=size,
                )
            )
        return tuple(entries)

    @staticmethod
    def _derive_parent_path(current_path: str | None) -> str | None:
        if not current_path:
            return None
        trimmed = current_path.strip("/")
        if not trimmed:
            return None
        parts = [segment for segment in trimmed.split("/") if segment]
        if len(parts) <= 1:
            return None
        return "/".join(parts[:-1])


def get_soulseek_ui_service(
    request: Request,
    config: AppConfig = Depends(get_app_config),
    client: SoulseekClient = Depends(get_soulseek_client),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> SoulseekUiService:
    """FastAPI dependency returning the Soulseek UI service."""

    return SoulseekUiService(
        request=request,
        config=config,
        soulseek_client=client,
        registry=registry,
    )


__all__ = [
    "SoulseekUiService",
    "SoulseekUploadRow",
    "SoulseekUserProfile",
    "SoulseekUserDirectoryEntry",
    "SoulseekUserFileEntry",
    "SoulseekUserDirectoryListing",
    "get_soulseek_ui_service",
]
