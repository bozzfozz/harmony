"""Factory helpers for wiring OAuth transaction stores."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.logging import get_logger

from .store_fs import FsOAuthTransactionStore
from .store_memory import MemoryOAuthTransactionStore
from .transactions import OAuthTransactionStore, TransactionStoreError

__all__ = ["get_oauth_store", "startup_check_oauth_store"]

logger = get_logger(__name__)


def _resolve_ttl_seconds(config: AppConfig) -> int:
    seconds = getattr(config.oauth, "state_ttl_seconds", None)
    if isinstance(seconds, int) and seconds > 0:
        return seconds
    return max(1, int(config.oauth.session_ttl_minutes * 60))


def get_oauth_store(
    config: AppConfig,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> OAuthTransactionStore:
    ttl_seconds = _resolve_ttl_seconds(config)
    ttl = timedelta(seconds=ttl_seconds)
    if getattr(config.oauth, "split_mode", False):
        base_dir = Path(getattr(config.oauth, "state_dir", "/config/runtime/oauth_state"))
        hash_cv = getattr(config.oauth, "store_hash_code_verifier", True)
        if hash_cv:
            raise TransactionStoreError(
                "OAUTH_MISCONFIG_FS_STORE: OAUTH_STORE_HASH_CV must be false in split mode"
            )
        return FsOAuthTransactionStore(
            base_dir,
            ttl=ttl,
            hash_code_verifier=hash_cv,
            now_fn=now_fn,
        )
    return MemoryOAuthTransactionStore(ttl=ttl, now_fn=now_fn)


def startup_check_oauth_store(
    store: OAuthTransactionStore,
    *,
    split_mode: bool,
) -> dict[str, Any]:
    if hasattr(store, "startup_check"):
        try:
            result = store.startup_check()  # type: ignore[call-arg]
        except Exception as exc:  # pragma: no cover - safety
            logger.error(
                "OAuth store startup check failed",
                extra={"event": "oauth.store.startup_failed", "error": str(exc)},
            )
            raise
        logger.info(
            "OAuth store startup check succeeded",
            extra={
                "event": "oauth.store.startup_ok",
                "backend": result.get("backend", "unknown"),
                "details": result,
            },
        )
        return result
    if split_mode:
        raise TransactionStoreError("OAUTH_MISCONFIG_FS_STORE: filesystem store required")
    return {
        "backend": "memory",
        "ttl_seconds": int(store.ttl.total_seconds()),
    }
