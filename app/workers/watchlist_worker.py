"""Asynchronous background worker that watches artists for new releases."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.config import WatchlistWorkerConfig
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.logging import get_logger
from app.services.watchlist_dao import WatchlistArtistRow, WatchlistDAO
from app.utils.activity import record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers.sync_worker import SyncWorker

logger = get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 86_400.0
MIN_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class WatchlistTaskOutcome:
    """Result snapshot for a processed artist."""

    artist: WatchlistArtistRow
    status: str
    queued: int
    attempts: int
    duration_ms: int
    reason: str | None = None


class WatchlistFailure(Exception):
    """Internal error wrapper indicating how the worker should react."""

    __slots__ = ("status", "retryable")

    def __init__(self, status: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class WatchlistWorker:
    """Monitor artists for new Spotify releases and queue missing tracks."""

    def __init__(
        self,
        *,
        spotify_client: SpotifyClient,
        soulseek_client: SoulseekClient,
        sync_worker: SyncWorker,
        config: WatchlistWorkerConfig,
        interval_seconds: float | None = None,
        dao: WatchlistDAO | None = None,
    ) -> None:
        self._spotify = spotify_client
        self._soulseek = soulseek_client
        self._sync = sync_worker
        self._config = config
        interval = float(interval_seconds or DEFAULT_INTERVAL_SECONDS)
        self._interval = max(interval, MIN_INTERVAL_SECONDS)
        self._dao = dao or WatchlistDAO()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._running = False
        self._rng = random.Random()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if self._running:
            return
        self._running = True
        self._stop_event = asyncio.Event()
        record_worker_started("watchlist")
        mark_worker_status("watchlist", "running")
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        was_running = self._running
        self._running = False
        self._stop_event.set()
        task = self._task
        if task is not None:
            grace_seconds = max(self._config.shutdown_grace_ms, 0) / 1000.0
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=grace_seconds)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            finally:
                self._task = None
        mark_worker_status("watchlist", WORKER_STOPPED)
        if was_running or task is not None:
            record_worker_stopped("watchlist")

    async def run_once(self) -> list[WatchlistTaskOutcome]:
        """Execute a single polling iteration (primarily for tests)."""

        return await self._process_watchlist()

    async def _run(self) -> None:
        logger.info(
            "WatchlistWorker started interval=%.0fs concurrency=%d max_per_tick=%d",
            self._interval,
            self._config.concurrency,
            self._config.max_per_tick,
        )
        try:
            while self._running and not self._stop_event.is_set():
                await self._process_watchlist()
                if self._stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:  # pragma: no cover - lifecycle management
            raise
        finally:
            running = self._running
            self._running = False
            if running:
                mark_worker_status("watchlist", WORKER_STOPPED)
                record_worker_stopped("watchlist")
            logger.info("WatchlistWorker stopped")

    async def _process_watchlist(self) -> list[WatchlistTaskOutcome]:
        record_worker_heartbeat("watchlist")
        start = time.monotonic()
        deadline = start + max(self._config.tick_budget_ms, 0) / 1000.0
        now = datetime.utcnow()
        artists = await self._dao.load_batch(self._config.max_per_tick, cutoff=now)
        if not artists:
            logger.debug("event=watchlist.tick status=idle count=0")
            return []

        semaphore = asyncio.Semaphore(max(1, self._config.concurrency))
        tasks = [
            asyncio.create_task(self._process_artist(artist, semaphore, deadline))
            for artist in artists
            if not self._deadline_exhausted(deadline)
        ]
        if not tasks:
            logger.debug("event=watchlist.tick status=skipped reason=no_budget")
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        outcomes: list[WatchlistTaskOutcome] = []
        for artist, result in zip(artists, results):
            if isinstance(result, WatchlistTaskOutcome):
                outcomes.append(result)
            elif isinstance(result, Exception):
                if isinstance(result, asyncio.CancelledError):
                    reason = "cancelled"
                    status = "cancelled"
                else:
                    reason = f"{type(result).__name__}: {result}"
                    status = "internal_error"
                logger.exception(
                    "event=watchlist.task artist_id=%s status=%s reason=%s",
                    artist.spotify_artist_id,
                    status,
                    reason,
                )
                await self._dao.mark_failed(
                    artist.id,
                    reason=status,
                    retry_at=datetime.utcnow(),
                )
                outcomes.append(
                    WatchlistTaskOutcome(
                        artist=artist,
                        status=status,
                        queued=0,
                        attempts=1,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        reason=reason,
                    )
                )

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "event=watchlist.tick status=done count=%d duration_ms=%d budget_ms=%d concurrency=%d",
            len(outcomes),
            duration_ms,
            self._config.tick_budget_ms,
            self._config.concurrency,
        )
        return outcomes

    async def _process_artist(
        self,
        artist: WatchlistArtistRow,
        semaphore: asyncio.Semaphore,
        deadline: float,
    ) -> WatchlistTaskOutcome:
        attempts = 0
        queued = 0
        status = "noop"
        reason: str | None = None
        start = time.monotonic()
        backoff_ms = 0

        if not await self._dao.mark_in_progress(artist.id):
            return WatchlistTaskOutcome(
                artist=artist,
                status="skipped",
                queued=0,
                attempts=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                reason="missing",
            )

        async with semaphore:
            while attempts < max(1, self._config.backoff_max_tries):
                attempts += 1
                if self._stop_event.is_set():
                    status = "cancelled"
                    reason = "shutdown"
                    break
                if self._deadline_exhausted(deadline):
                    status = "timeout"
                    reason = "tick_budget_exceeded"
                    break
                try:
                    queued = await self._process_artist_once(artist, deadline)
                except WatchlistFailure as failure:
                    status = failure.status
                    reason = str(failure)
                    if not failure.retryable or attempts >= self._config.backoff_max_tries:
                        break
                    backoff_ms = self._calculate_backoff_ms(attempts)
                    await self._sleep_with_deadline(backoff_ms / 1000.0, deadline)
                    continue
                else:
                    status = "ok" if queued else "noop"
                    reason = None
                    await self._dao.mark_success(artist.id, checked_at=datetime.utcnow())
                    break

        duration_ms = int((time.monotonic() - start) * 1000)
        if status in {"ok", "noop"}:
            logger.info(
                "event=watchlist.task artist_id=%s status=%s queued=%d attempts=%d duration_ms=%d",
                artist.spotify_artist_id,
                status,
                queued,
                attempts,
                duration_ms,
            )
        else:
            retry_at = None
            if status in {"timeout", "dependency_error"}:
                if backoff_ms <= 0:
                    backoff_ms = self._calculate_backoff_ms(attempts)
                retry_at = datetime.utcnow() + timedelta(milliseconds=backoff_ms)
            await self._dao.mark_failed(
                artist.id,
                reason=status,
                retry_at=retry_at,
            )
            logger.warning(
                "event=watchlist.task artist_id=%s status=%s attempts=%d duration_ms=%d reason=%s",
                artist.spotify_artist_id,
                status,
                attempts,
                duration_ms,
                reason,
            )

        return WatchlistTaskOutcome(
            artist=artist,
            status=status,
            queued=queued,
            attempts=attempts,
            duration_ms=duration_ms,
            reason=reason,
        )

    async def _process_artist_once(
        self,
        artist: WatchlistArtistRow,
        deadline: float,
    ) -> int:
        if self._deadline_exhausted(deadline):
            raise WatchlistFailure("timeout", "tick budget exceeded", retryable=True)

        try:
            albums = await asyncio.to_thread(
                self._spotify.get_artist_albums, artist.spotify_artist_id
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            raise WatchlistFailure(
                "dependency_error", f"spotify albums failed: {exc}", retryable=True
            )

        last_checked = artist.last_checked
        recent_albums = [album for album in albums if self._is_new_release(album, last_checked)]
        if not recent_albums:
            return 0

        track_candidates: List[Tuple[dict[str, Any], dict[str, Any]]] = []
        for album in recent_albums:
            album_id = str(album.get("id") or "").strip()
            if not album_id:
                continue
            try:
                tracks = await asyncio.to_thread(self._spotify.get_album_tracks, album_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                raise WatchlistFailure(
                    "dependency_error",
                    f"spotify album tracks failed: {exc}",
                    retryable=True,
                )
            for track in tracks:
                track_id = str(track.get("id") or "").strip()
                if not track_id:
                    continue
                track_candidates.append((album, track))

        if not track_candidates:
            return 0

        track_ids = [str(track.get("id")) for _, track in track_candidates if track.get("id")]
        existing = await self._dao.load_existing_track_ids(track_ids)
        scheduled: set[str] = set()
        queued = 0

        for album, track in track_candidates:
            if self._deadline_exhausted(deadline):
                raise WatchlistFailure("timeout", "tick budget exceeded", retryable=True)

            track_id = str(track.get("id") or "").strip()
            if not track_id or track_id in existing or track_id in scheduled:
                continue
            scheduled.add(track_id)
            created = await self._schedule_download(artist, album, track)
            if created:
                queued += 1

        return queued

    async def _schedule_download(
        self,
        artist: WatchlistArtistRow,
        album: dict[str, Any],
        track: dict[str, Any],
    ) -> bool:
        query = self._build_search_query(artist.name, album, track)
        if not query:
            return False
        try:
            results = await asyncio.wait_for(
                self._soulseek.search(query),
                timeout=max(self._config.search_timeout_ms, 1) / 1000.0,
            )
        except asyncio.TimeoutError:
            raise WatchlistFailure("timeout", f"search timeout for {query}", retryable=True)
        except Exception as exc:  # pragma: no cover - defensive logging
            raise WatchlistFailure(
                "dependency_error", f"search failed for {query}: {exc}", retryable=True
            )

        username, file_info = self._select_candidate(results)
        if not username or not file_info:
            logger.info(
                "event=watchlist.search artist_id=%s status=empty query=%s",
                artist.spotify_artist_id,
                query,
            )
            return False

        payload = dict(file_info)
        filename = str(
            payload.get("filename") or payload.get("name") or track.get("name") or "unknown"
        )
        priority = self._extract_priority(payload)
        track_id = str(track.get("id") or "").strip()
        album_id = str(album.get("id") or "").strip()

        download_id = await self._dao.create_download_record(
            username=username,
            filename=filename,
            priority=priority,
            spotify_track_id=track_id,
            spotify_album_id=album_id,
            payload=payload,
        )
        if download_id is None:
            raise WatchlistFailure(
                "internal_error",
                f"failed to persist download for {filename}",
                retryable=False,
            )

        payload["download_id"] = download_id
        payload.setdefault("filename", filename)
        payload["priority"] = priority

        job = {
            "username": username,
            "files": [payload],
            "priority": priority,
            "source": "watchlist",
        }
        try:
            await self._sync.enqueue(job)
        except Exception as exc:  # pragma: no cover - defensive logging
            await self._dao.mark_download_failed(download_id, str(exc))
            raise WatchlistFailure(
                "dependency_error",
                f"failed to enqueue download {download_id}: {exc}",
                retryable=True,
            )

        logger.info(
            "event=watchlist.download artist_id=%s track_id=%s status=queued",
            artist.spotify_artist_id,
            track_id,
        )
        return True

    def _calculate_backoff_ms(self, attempt: int) -> int:
        base = max(self._config.backoff_base_ms, 0)
        exponent = max(attempt - 1, 0)
        delay = base * (2**exponent)
        jitter = self._config.jitter_pct
        if delay <= 0 or jitter <= 0:
            return max(int(delay), 0)
        spread = delay * jitter
        jitter_value = self._rng.uniform(-spread, spread)
        return max(int(delay + jitter_value), 0)

    def _deadline_exhausted(self, deadline: float | None) -> bool:
        if deadline is None:
            return False
        return time.monotonic() >= deadline

    async def _sleep_with_deadline(self, seconds: float, deadline: float | None) -> None:
        if seconds <= 0:
            return
        end_time = time.monotonic() + seconds
        if deadline is not None:
            end_time = min(end_time, deadline)
        while True:
            if self._stop_event.is_set():
                return
            remaining = end_time - time.monotonic()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=remaining)
                return
            except asyncio.TimeoutError:
                return

    @staticmethod
    def _extract_priority(payload: Dict[str, Any]) -> int:
        value = payload.get("priority")
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _select_candidate(result: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if isinstance(result, dict):
            entries = result.get("results")
            if isinstance(entries, list):
                for entry in entries:
                    username, file_info = WatchlistWorker._extract_candidate(entry)
                    if username and file_info:
                        return username, file_info
        elif isinstance(result, list):
            for entry in result:
                username, file_info = WatchlistWorker._extract_candidate(entry)
                if username and file_info:
                    return username, file_info
        return None, None

    @staticmethod
    def _extract_candidate(candidate: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if not isinstance(candidate, dict):
            return None, None
        username = candidate.get("username")
        files = candidate.get("files")
        if isinstance(files, list):
            for file_info in files:
                if isinstance(file_info, dict):
                    enriched = dict(file_info)
                    if "filename" not in enriched and "name" in enriched:
                        enriched["filename"] = enriched["name"]
                    return username, enriched
        return None, None

    @staticmethod
    def _build_search_query(
        artist_name: str,
        album: Dict[str, Any],
        track: Dict[str, Any],
    ) -> str:
        parts: List[str] = []
        candidate_artist = artist_name or WatchlistWorker._primary_artist(track, album)
        if candidate_artist:
            parts.append(candidate_artist.strip())
        title = track.get("name") or track.get("title")
        if title:
            parts.append(str(title).strip())
        album_name = album.get("name")
        if album_name:
            parts.append(str(album_name).strip())
        return " ".join(part for part in parts if part)

    @staticmethod
    def _primary_artist(track: Dict[str, Any], album: Dict[str, Any]) -> str:
        def _extract_artist(collection: Iterable[Dict[str, Any]] | None) -> str:
            if not collection:
                return ""
            for artist in collection:
                if isinstance(artist, dict) and artist.get("name"):
                    return str(artist["name"])
            return ""

        artists = track.get("artists") if isinstance(track.get("artists"), list) else None
        name = _extract_artist(artists)
        if name:
            return name
        album_artists = album.get("artists") if isinstance(album.get("artists"), list) else None
        return _extract_artist(album_artists)

    @staticmethod
    def _is_new_release(album: Dict[str, Any], last_checked: Optional[datetime]) -> bool:
        if last_checked is None:
            return True
        release_date = WatchlistWorker._parse_release_date(album)
        if release_date is None:
            return False
        return release_date > last_checked

    @staticmethod
    def _parse_release_date(album: Dict[str, Any]) -> Optional[datetime]:
        value = album.get("release_date")
        if not value:
            return None
        precision = (album.get("release_date_precision") or "day").lower()
        try:
            if precision == "day":
                return datetime.strptime(str(value), "%Y-%m-%d")
            if precision == "month":
                return datetime.strptime(str(value), "%Y-%m")
            if precision == "year":
                return datetime.strptime(str(value), "%Y")
        except ValueError:
            return None
        return None


__all__ = ["WatchlistWorker", "WatchlistTaskOutcome", "WatchlistFailure"]
