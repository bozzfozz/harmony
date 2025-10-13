"""Common schema primitives shared across API surface."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar, Self
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    field_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema


class _ValidatedString(str):
    """Base helper implementing Pydantic v2 hooks for string wrappers."""

    _json_schema_extra: ClassVar[dict[str, Any]] = {"type": "string"}

    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(cls.validate, handler(str))

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema.update(cls._json_schema_extra)
        return json_schema

    @classmethod
    def validate(cls, value: Any) -> Self:
        raise NotImplementedError


class ID(_ValidatedString):
    """Identifier exposed via the public API."""

    _json_schema_extra: ClassVar[dict[str, Any]] = {"type": "string", "title": "ID"}

    @classmethod
    def validate(cls, value: Any) -> ID:
        if isinstance(value, cls):
            return value
        if isinstance(value, bytes | bytearray):
            value = value.decode()
        if not isinstance(value, str):
            raise TypeError("identifier must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("identifier must not be empty")
        return cls(stripped)


class URI(_ValidatedString):
    """Simple URI wrapper performing light validation."""

    _json_schema_extra: ClassVar[dict[str, Any]] = {
        "type": "string",
        "format": "uri",
        "title": "URI",
    }

    @classmethod
    def validate(cls, value: Any) -> URI:
        if isinstance(value, cls):
            return value
        if isinstance(value, bytes | bytearray):
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


class ISODateTime(_ValidatedString):
    """Datetime serialised to ISO8601 string."""

    _json_schema_extra: ClassVar[dict[str, Any]] = {
        "type": "string",
        "format": "date-time",
        "title": "ISODateTime",
    }

    @classmethod
    def validate(cls, value: Any) -> ISODateTime:
        if isinstance(value, cls):
            return value
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return cls(value.isoformat())
        if isinstance(value, bytes | bytearray):
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
            parsed = parsed.replace(tzinfo=UTC)
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
    details: dict[str, Any] | None = None
    timestamp: ISODateTime = Field(default_factory=lambda: ISODateTime.validate(datetime.now(UTC)))

    @field_validator("code", "message")
    @classmethod
    def _ensure_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator("details", mode="before")
    @classmethod
    def _normalise_details(cls, value: Any) -> dict[str, Any] | None:
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
