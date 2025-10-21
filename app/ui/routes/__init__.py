from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/ui", tags=["UI"])

from . import base  # noqa: E402  # isort: skip
from . import events  # noqa: E402  # isort: skip
from . import operations  # noqa: E402  # isort: skip
from . import soulseek  # noqa: E402  # isort: skip
from . import spotify  # noqa: E402  # isort: skip
from . import system  # noqa: E402  # isort: skip
from app.ui import router as legacy_router  # noqa: E402  # isort: skip

router.include_router(base.router, tags=["UI"])
router.include_router(events.router, tags=["UI"])
router.include_router(operations.router, tags=["UI"])
router.include_router(soulseek.router, tags=["UI"])
router.include_router(spotify.router, tags=["UI"])
router.include_router(system.router, tags=["UI"])
router.include_router(legacy_router.router, tags=["UI"])

__all__ = ["router"]
