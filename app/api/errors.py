"""Backward compatible import wrapper for exception handlers."""

from app.middleware.errors import setup_exception_handlers

__all__ = ["setup_exception_handlers"]
