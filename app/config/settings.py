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

    def _load_config_section(self, section: str) -> Dict[str, Any]:
        """Load a section from the Harmony config file."""

        file_path = Path(os.getenv("HARMONY_CONFIG", "config.json"))
        config = self._load_from_file(file_path)
        section_data = config.get(section, {}) if isinstance(config, dict) else {}
        if isinstance(section_data, dict):
            return section_data
        return {}

    def get_soulseek_config(self) -> Dict[str, Any]:
        """Return the slskd configuration merged from environment and file overrides."""

        with self._lock:
            cache_key = "soulseek"
            if cache_key not in self._cache:
                file_config = self._load_config_section("soulseek")
                env_config = {
                    "slskd_url": os.getenv("SLSKD_URL", ""),
                    "api_key": os.getenv("SLSKD_API_KEY", ""),
                    "download_path": os.getenv("SLSKD_DOWNLOAD_PATH", "./downloads"),
                }

                merged = {**file_config, **env_config}
                self._cache[cache_key] = merged
            return dict(self._cache[cache_key])

    def get_beets_env(self) -> Dict[str, str]:
        """Return environment overrides for beets CLI commands."""

        with self._lock:
            cache_key = "beets_env"
            if cache_key not in self._cache:
                env: Dict[str, str] = {}

                file_config = self._load_config_section("beets")
                file_env = file_config.get("env", {}) if isinstance(file_config, dict) else {}
                if isinstance(file_env, dict):
                    env.update({str(k): str(v) for k, v in file_env.items() if v not in (None, "")})

                overrides = {
                    "BEETSCONFIG": os.getenv("BEETS_CONFIG"),
                    "BEETSDIR": os.getenv("BEETS_LIBRARY"),
                }

                env.update({key: value for key, value in overrides.items() if value})
                self._cache[cache_key] = env

            return dict(self._cache[cache_key])


config_manager = ConfigManager()

