from __future__ import annotations

import json
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.utils.logging_config import get_logger

logger = get_logger("settings_router")
router = APIRouter()

CONFIG_FILE = "config/config.json"


class SettingsUpdate(BaseModel):
    key: str
    value: Any


def load_config() -> Dict[str, Any]:
    """Load configuration from file."""
    try:
        if not os.path.exists(CONFIG_FILE):
            logger.warning("Config file not found, creating default")
            return {}
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to load config: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load config") from exc


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file."""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        logger.info("Configuration saved successfully")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to save config: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save config") from exc


@router.get("/config")
def get_settings() -> Dict[str, Any]:
    """Return the current configuration."""
    config = load_config()
    logger.info("System configuration retrieved")
    return {"status": "success", "config": config}


@router.post("/config")
def update_settings(update: SettingsUpdate) -> Dict[str, Any]:
    """Update a specific config key/value."""
    config = load_config()
    config[update.key] = update.value
    save_config(config)
    logger.info("Updated config: %s = %s", update.key, update.value)
    return {"status": "success", "updated": {update.key: update.value}}


@router.delete("/config/{key}")
def delete_setting(key: str) -> Dict[str, Any]:
    """Delete a config key from the configuration."""
    config = load_config()
    if key not in config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    removed_value = config.pop(key)
    save_config(config)
    logger.info("Deleted config key: %s", key)
    return {"status": "success", "removed": {key: removed_value}}
