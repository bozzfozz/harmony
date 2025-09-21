"""Logging configuration utilities for the Harmony FastAPI application."""
from __future__ import annotations

import logging
from typing import Dict

_LOGGER_CACHE: Dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """Return a configured :class:`logging.Logger` instance.

    The function ensures that loggers are created with a consistent
    configuration across the project. Multiple calls with the same
    ``name`` will always return the same logger instance. Loggers are
    configured lazily to avoid interfering with user-configured logging
    settings when the module is imported.
    """

    if name in _LOGGER_CACHE:
        return _LOGGER_CACHE[name]

    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    logger.propagate = False

    _LOGGER_CACHE[name] = logger
    return logger


__all__ = ["get_logger"]
