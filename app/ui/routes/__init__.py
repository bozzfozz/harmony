from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/ui", tags=["UI"])

from . import activity  # noqa: E402  # isort: skip
from . import admin  # noqa: E402  # isort: skip
from . import base  # noqa: E402  # isort: skip
from . import downloads  # noqa: E402  # isort: skip
from . import events  # noqa: E402  # isort: skip
from . import jobs  # noqa: E402  # isort: skip
from . import operations  # noqa: E402  # isort: skip
from . import search  # noqa: E402  # isort: skip
from . import settings  # noqa: E402  # isort: skip
from . import soulseek  # noqa: E402  # isort: skip
from . import spotify  # noqa: E402  # isort: skip
from . import system  # noqa: E402  # isort: skip
from . import watchlist  # noqa: E402  # isort: skip

router.include_router(base.router, tags=["UI"])
router.include_router(admin.router, tags=["UI"])
router.include_router(operations.router, tags=["UI"])
router.include_router(search.router, tags=["UI"])
router.include_router(settings.router, tags=["UI"])
router.include_router(downloads.router, tags=["UI"])
router.include_router(jobs.router, tags=["UI"])
router.include_router(watchlist.router, tags=["UI"])
router.include_router(activity.router, tags=["UI"])
router.include_router(events.router, tags=["UI"])
router.include_router(soulseek.router, tags=["UI"])
router.include_router(spotify.router, tags=["UI"])
router.include_router(system.router, tags=["UI"])

__all__ = ["router"]
