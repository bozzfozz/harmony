"""Compatibility shim exposing :mod:`app.api.system`."""

from app.api.system import psutil, router

__all__ = ["router", "psutil"]
