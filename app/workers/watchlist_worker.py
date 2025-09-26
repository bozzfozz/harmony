"""Background worker that watches Spotify artists for new releases."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select

from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download, WatchlistArtist
from app.utils.activity import record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers.sync_worker import SyncWorker

logger = get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 86_400.0
MIN_INTERVAL_SECONDS = 60.0


class WatchlistWorker:
    """Monitor artists for new Spotify releases and queue missing tracks."""

    def __init__(
        self,
        *,
        spotify_client: SpotifyClient,
        soulseek_client: SoulseekClient,
        sync_worker: SyncWorker,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._spotify = spotify_client
        self._soulseek = soulseek_client
        self._sync = sync_worker
        self._interval = max(
            float(interval_seconds or DEFAULT_INTERVAL_SECONDS), MIN_INTERVAL_SECONDS
        )
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._running = False

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
            try:
                await task
            finally:
                self._task = None
        mark_worker_status("watchlist", WORKER_STOPPED)
        if was_running or task is not None:
            record_worker_stopped("watchlist")

    async def run_once(self) -> None:
        """Execute a single polling iteration (primarily for tests)."""

        await self._process_watchlist()

    async def _run(self) -> None:
        logger.info("WatchlistWorker started (interval %.0fs)", self._interval)
        try:
            while self._running:
                await self._process_watchlist()
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

    async def _process_watchlist(self) -> None:
        record_worker_heartbeat("watchlist")
        with session_scope() as session:
            artists = session.execute(select(WatchlistArtist)).scalars().all()
        if not artists:
            logger.debug("No watchlist artists to process")
            return

        for artist in artists:
            try:
                await self._process_artist(artist)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to process watchlist artist %s: %s",
                    artist.spotify_artist_id,
                    exc,
                )

    async def _process_artist(self, artist: WatchlistArtist) -> None:
        logger.debug(
            "Processing watchlist artist %s (last_checked=%s)",
            artist.spotify_artist_id,
            artist.last_checked,
        )
        try:
            albums = await asyncio.to_thread(
                self._spotify.get_artist_albums, artist.spotify_artist_id
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "Spotify lookup failed for artist %s: %s",
                artist.spotify_artist_id,
                exc,
            )
            return

        last_checked = artist.last_checked
        recent_albums = [album for album in albums if self._is_new_release(album, last_checked)]
        if not recent_albums:
            self._update_last_checked(artist.id)
            return

        track_candidates: List[Tuple[dict[str, Any], dict[str, Any]]] = []
        for album in recent_albums:
            album_id = str(album.get("id") or "").strip()
            if not album_id:
                continue
            try:
                tracks = await asyncio.to_thread(self._spotify.get_album_tracks, album_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to fetch tracks for album %s: %s",
                    album_id,
                    exc,
                )
                continue
            for track in tracks:
                track_id = str(track.get("id") or "").strip()
                if not track_id:
                    continue
                track_candidates.append((album, track))

        if not track_candidates:
            self._update_last_checked(artist.id)
            return

        track_ids = [str(track.get("id")) for _, track in track_candidates if track.get("id")]
        existing = self._load_existing_track_ids(track_ids)
        scheduled: set[str] = set()
        queued = 0
        for album, track in track_candidates:
            track_id = str(track.get("id") or "").strip()
            if not track_id or track_id in existing or track_id in scheduled:
                continue
            scheduled.add(track_id)
            if await self._schedule_download(artist, album, track):
                queued += 1

        logger.info(
            "Watchlist artist %s: queued %d new track(s)",
            artist.spotify_artist_id,
            queued,
        )
        self._update_last_checked(artist.id)

    def _update_last_checked(self, artist_id: int) -> None:
        with session_scope() as session:
            record = session.get(WatchlistArtist, int(artist_id))
            if record is None:
                return
            record.last_checked = datetime.utcnow()
            session.add(record)

    def _load_existing_track_ids(self, track_ids: Sequence[str]) -> set[str]:
        if not track_ids:
            return set()
        with session_scope() as session:
            results = (
                session.execute(
                    select(Download.spotify_track_id)
                    .where(Download.spotify_track_id.in_(track_ids))
                    .where(Download.state.notin_(["failed", "cancelled", "dead_letter"]))
                )
                .scalars()
                .all()
            )
        return {str(value) for value in results if value}

    async def _schedule_download(
        self,
        artist: WatchlistArtist,
        album: dict[str, Any],
        track: dict[str, Any],
    ) -> bool:
        query = self._build_search_query(artist.name, album, track)
        if not query:
            return False
        try:
            results = await self._soulseek.search(query)
        except Exception as exc:  # pragma: no cover - network failure handling
            logger.warning("Soulseek search failed for %s: %s", query, exc)
            return False

        username, file_info = self._select_candidate(results)
        if not username or not file_info:
            logger.info(
                "No Soulseek candidate found for watchlist track %s (%s)",
                track.get("name"),
                track.get("id"),
            )
            return False

        payload = dict(file_info)
        filename = str(
            payload.get("filename") or payload.get("name") or track.get("name") or "unknown"
        )
        priority = self._extract_priority(payload)
        track_id = str(track.get("id") or "").strip()
        album_id = str(album.get("id") or "").strip()

        download_id = self._create_download_record(
            username=username,
            filename=filename,
            priority=priority,
            spotify_track_id=track_id,
            spotify_album_id=album_id,
            payload=payload,
        )
        if download_id is None:
            return False

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
            logger.error(
                "Failed to enqueue watchlist download %s: %s",
                download_id,
                exc,
            )
            self._mark_download_failed(download_id, str(exc))
            return False

        logger.info(
            "Queued watchlist download for %s - %s",
            artist.name,
            track.get("name"),
        )
        return True

    def _create_download_record(
        self,
        *,
        username: str,
        filename: str,
        priority: int,
        spotify_track_id: str,
        spotify_album_id: str,
        payload: Dict[str, Any],
    ) -> Optional[int]:
        try:
            with session_scope() as session:
                download = Download(
                    filename=filename,
                    state="queued",
                    progress=0.0,
                    username=username,
                    priority=priority,
                    spotify_track_id=spotify_track_id or None,
                    spotify_album_id=spotify_album_id or None,
                )
                session.add(download)
                session.flush()
                payload_copy = dict(payload)
                payload_copy.setdefault("filename", filename)
                payload_copy["download_id"] = download.id
                payload_copy["priority"] = priority
                download.request_payload = payload_copy
                session.add(download)
                return download.id
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to create download record for %s: %s", filename, exc)
            return None

    def _mark_download_failed(self, download_id: int, reason: str) -> None:
        with session_scope() as session:
            record = session.get(Download, int(download_id))
            if record is None:
                return
            record.state = "failed"
            record.updated_at = datetime.utcnow()
            payload = dict(record.request_payload or {})
            payload["error"] = reason
            record.request_payload = payload
            session.add(record)

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
