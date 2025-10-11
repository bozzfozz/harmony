"""Error schema definitions reused across routers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.schemas.common import ProblemDetail


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(BaseModel):
    """API error payload conforming to the canonical contract."""

    error: ProblemDetail

    @classmethod
    def from_components(
        cls,
        *,
        code: ErrorCode,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> "ApiError":
        return cls(error=ProblemDetail(code=code.value, message=message, details=details))


__all__ = ["ApiError", "ErrorCode"]
