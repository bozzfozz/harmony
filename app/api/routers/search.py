"""Compatibility shim exposing :mod:`app.api.search`."""

from app.api import search as _search

router = _search.router


def log_event(*args, **kwargs):
    """Delegate to :mod:`app.api.search`'s active event logger."""

    _search.log_event(*args, **kwargs)


__all__ = ["router", "log_event"]
