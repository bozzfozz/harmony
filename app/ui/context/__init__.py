from __future__ import annotations

from . import (
    admin as _admin,
    auth as _auth,
    base as _base,
    common as _common,
    dashboard as _dashboard,
    downloads as _downloads,
    jobs as _jobs,
    operations as _operations,
    search as _search,
    settings as _settings,
    soulseek as _soulseek,
    spotify as _spotify,
    system as _system,
)
from .admin import *  # noqa: F401,F403
from .auth import *  # noqa: F401,F403
from .base import *  # noqa: F401,F403
from .common import *  # noqa: F401,F403
from .dashboard import *  # noqa: F401,F403
from .downloads import *  # noqa: F401,F403
from .jobs import *  # noqa: F401,F403
from .operations import *  # noqa: F401,F403
from .search import *  # noqa: F401,F403
from .settings import *  # noqa: F401,F403
from .soulseek import *  # noqa: F401,F403
from .spotify import *  # noqa: F401,F403
from .system import *  # noqa: F401,F403

__all__ = [
    *_base.__all__,
    *_auth.__all__,
    *_common.__all__,
    *_admin.__all__,
    *_dashboard.__all__,
    *_downloads.__all__,
    *_jobs.__all__,
    *_operations.__all__,
    *_search.__all__,
    *_settings.__all__,
    *_system.__all__,
    *_spotify.__all__,
    *_soulseek.__all__,
]
