from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Dict

from app.utils.logging_config import get_logger


logger = get_logger("config")


class ConfigManager:
    """Simple configuration manager for runtime settings."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._cache: Dict[str, Any] = {}

    def _load_from_file(self, file_path: Path) -> Dict[str, Any]:
        if not file_path.exists():
            return {}
        try:
            return json.loads(file_path.read_text())
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse configuration file", exc_info=exc)
        except OSError as exc:
            logger.error("Unable to read configuration file", exc_info=exc)
        return {}

    def get_soulseek_config(self) -> Dict[str, Any]:
        """Return the slskd configuration merged from environment and file overrides."""

        with self._lock:
            cache_key = "soulseek"
            if cache_key not in self._cache:
                file_config = self._load_from_file(Path(os.getenv("HARMONY_CONFIG", "config.json")))
                env_config = {
                    "slskd_url": os.getenv("SLSKD_URL", ""),
                    "api_key": os.getenv("SLSKD_API_KEY", ""),
                    "download_path": os.getenv("SLSKD_DOWNLOAD_PATH", "./downloads"),
                }

                merged = {**file_config.get("soulseek", {}), **env_config}
                self._cache[cache_key] = merged
            return dict(self._cache[cache_key])


config_manager = ConfigManager()

