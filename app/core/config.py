"""Static configuration defaults for Harmony settings."""
from __future__ import annotations

from typing import Mapping

DEFAULT_SETTINGS: Mapping[str, str] = {
    "sync_worker_concurrency": "1",
    "matching_worker_batch_size": "10",
    "autosync_min_bitrate": "192",
    "autosync_preferred_formats": "mp3,flac",
}

__all__ = ["DEFAULT_SETTINGS"]
