"""Filesystem-backed OAuth transaction store for split deployments."""

from __future__ import annotations

import errno
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .transactions import (
    OAuthTransactionStore,
    Transaction,
    TransactionExpiredError,
    TransactionNotFoundError,
    TransactionStoreError,
    TransactionUsedError,
)

__all__ = ["FsOAuthTransactionStore"]

_JSON_VERSION = 1


class FsOAuthTransactionStore(OAuthTransactionStore):
    """Filesystem based transaction store with atomic operations."""

    def __init__(
        self,
        base_dir: str | os.PathLike[str],
        *,
        ttl: timedelta,
        hash_code_verifier: bool = True,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("OAuth transaction TTL must be positive")
        self._ttl = ttl
        self._hash_code_verifier = hash_code_verifier
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._base_dir = Path(base_dir).resolve()
        self._pending_dir = self._base_dir / "pending"
        self._consumed_dir = self._base_dir / "consumed"
        self._ensure_directories()

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def _ensure_directories(self) -> None:
        for directory in (self._base_dir, self._pending_dir, self._consumed_dir):
            directory.mkdir(mode=0o770, parents=True, exist_ok=True)

    def _transaction_path(self, directory: Path, state: str) -> Path:
        return directory / f"{state}.json"

    def _write_file(self, path: Path, payload: Mapping[str, Any]) -> None:
        tmp_dir = path.parent
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=tmp_dir,
            prefix=f".{path.stem}.",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            finally:
                raise

    def create(
        self,
        state: str,
        code_verifier: str,
        meta: Mapping[str, Any],
        ttl_seconds: int,
    ) -> None:
        if not state:
            raise TransactionStoreError("state must be provided")
        pending_path = self._transaction_path(self._pending_dir, state)
        consumed_path = self._transaction_path(self._consumed_dir, state)
        if pending_path.exists() or consumed_path.exists():
            raise TransactionUsedError(state)
        issued_at = self._now()
        expires_at = issued_at + timedelta(seconds=ttl_seconds)
        record = {
            "cv": self._hash(code_verifier) if self._hash_code_verifier else code_verifier,
            "meta": dict(meta),
            "exp": int(expires_at.timestamp()),
            "iat": int(issued_at.timestamp()),
            "ver": _JSON_VERSION,
        }
        self._write_file(pending_path, record)

    def _hash(self, code_verifier: str) -> str:
        import base64
        import hashlib

        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        encoded = base64.urlsafe_b64encode(digest).decode("ascii")
        return encoded.rstrip("=")

    def consume(self, state: str) -> Transaction:
        pending_path = self._transaction_path(self._pending_dir, state)
        consumed_path = self._transaction_path(self._consumed_dir, state)
        try:
            os.replace(pending_path, consumed_path)
        except FileNotFoundError:
            if consumed_path.exists():
                raise TransactionUsedError(state)
            raise TransactionNotFoundError(state)
        except OSError as exc:  # pragma: no cover - defensive
            if exc.errno == errno.EXDEV:
                raise TransactionStoreError("pending and consumed directories must share a filesystem")
            raise
        record = self._read_record(consumed_path)
        issued_at = datetime.fromtimestamp(record["iat"], tz=timezone.utc)
        expires_at = datetime.fromtimestamp(record["exp"], tz=timezone.utc)
        if self._hash_code_verifier:
            raise TransactionStoreError("code verifier is not stored when hashing is enabled")
        if self._now() >= expires_at:
            raise TransactionExpiredError(state)
        return Transaction(
            state=state,
            code_verifier=record["cv"],
            meta=dict(record.get("meta", {})),
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def _read_record(self, path: Path) -> Mapping[str, Any]:
        try:
            data = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise TransactionStoreError(f"invalid transaction file: {path}") from exc
        if not isinstance(data, dict):
            raise TransactionStoreError(f"invalid transaction payload: {path}")
        if data.get("ver") != _JSON_VERSION:
            raise TransactionStoreError(f"unsupported transaction version: {data.get('ver')}")
        return data

    def exists(self, state: str) -> bool:
        pending_path = self._transaction_path(self._pending_dir, state)
        consumed_path = self._transaction_path(self._consumed_dir, state)
        return pending_path.exists() or consumed_path.exists()

    def purge_expired(self, *, reference: datetime | None = None) -> int:
        moment = reference or self._now()
        removed = 0
        for entry in self._pending_dir.glob("*.json"):
            record = self._read_record(entry)
            expires_at = datetime.fromtimestamp(record["exp"], tz=timezone.utc)
            if moment >= expires_at:
                entry.unlink(missing_ok=True)
                removed += 1
        return removed

    def count(self) -> int:
        return sum(1 for _ in self._pending_dir.glob("*.json"))

    def describe(self) -> dict[str, Any]:
        mode = self._base_dir.stat().st_mode
        return {
            "backend": "fs",
            "base_dir": str(self._base_dir),
            "permissions": stat.filemode(mode),
            "pending": self.count(),
            "ttl_seconds": int(self._ttl.total_seconds()),
            "hash_code_verifier": self._hash_code_verifier,
            "writable": os.access(self._base_dir, os.W_OK),
        }

    def startup_check(self) -> dict[str, Any]:
        marker = f".check-{os.getpid()}-{int(self._now().timestamp())}"
        pending_marker = self._pending_dir / f"{marker}.tmp"
        consumed_marker = self._consumed_dir / f"{marker}.tmp"
        payload = {"ver": _JSON_VERSION, "cv": "", "meta": {}, "exp": 0, "iat": 0}
        self._write_file(pending_marker, payload)
        try:
            os.replace(pending_marker, consumed_marker)
        except OSError as exc:
            raise TransactionStoreError("failed to rename marker file") from exc
        finally:
            consumed_marker.unlink(missing_ok=True)
        return self.describe()
