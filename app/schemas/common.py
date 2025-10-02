"""Common schema primitives shared across API surface."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ID(str):
    """Identifier exposed via the public API."""

    @classmethod
    def __get_validators__(cls):  # pragma: no cover - pydantic hook
        yield cls.validate

    @classmethod
    def validate(cls, value: Any, _: Any = None) -> "ID":
        if isinstance(value, cls):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode()
        if not isinstance(value, str):
            raise TypeError("identifier must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("identifier must not be empty")
        return cls(stripped)


class URI(str):
    """Simple URI wrapper performing light validation."""

    @classmethod
    def __get_validators__(cls):  # pragma: no cover - pydantic hook
        yield cls.validate

    @classmethod
    def validate(cls, value: Any, _: Any = None) -> "URI":
        if isinstance(value, cls):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode()
        if not isinstance(value, str):
            raise TypeError("uri must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("uri must not be empty")
        parsed = urlparse(stripped)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("uri must include scheme and host")
        return cls(stripped)


class ISODateTime(str):
    """Datetime serialised to ISO8601 string."""

    @classmethod
    def __get_validators__(cls):  # pragma: no cover - pydantic hook
        yield cls.validate

    @classmethod
    def validate(cls, value: Any, _: Any = None) -> "ISODateTime":
        if isinstance(value, cls):
            return value
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return cls(value.isoformat())
        if isinstance(value, (bytes, bytearray)):
            value = value.decode()
        if not isinstance(value, str):
            raise TypeError("datetime must be string or datetime")
        stripped = value.strip()
        if not stripped:
            raise ValueError("datetime must not be empty")
        candidate = stripped.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError("invalid ISO 8601 datetime") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return cls(parsed.isoformat())


class SourceEnum(str, Enum):
    SPOTIFY = "spotify"
    SOULSEEK = "soulseek"
    LOCAL = "local"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class Sort(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str = Field(..., min_length=1)
    order: SortOrder = Field(default=SortOrder.ASC)


class Paging(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = Field(..., ge=0)
    offset: int = Field(..., ge=0)
    total: int = Field(..., ge=0)


class ProblemDetail(BaseModel):
    """Canonical error payload."""

    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: ISODateTime = Field(
        default_factory=lambda: ISODateTime.validate(datetime.now(timezone.utc))
    )

    @field_validator("code", "message")
    @classmethod
    def _ensure_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator("details", mode="before")
    @classmethod
    def _normalise_details(cls, value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            return dict(value)
        raise TypeError("details must be a mapping if provided")


__all__ = [
    "ID",
    "ISODateTime",
    "Paging",
    "ProblemDetail",
    "Sort",
    "SortOrder",
    "SourceEnum",
    "URI",
]
