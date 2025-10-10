"""Spotify client wrapper used by Harmony."""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional

from app.config import SpotifyConfig
from app.core.spotify_cache import SettingsCacheHandler
from app.logging import get_logger

try:  # pragma: no cover - import guard
    import spotipy
    from spotipy import Spotify
    from spotipy.exceptions import SpotifyException
    from spotipy.oauth2 import SpotifyOAuth
except Exception:  # pragma: no cover - during tests we mock the client
    spotipy = None
    Spotify = Any  # type: ignore
    SpotifyOAuth = Any  # type: ignore

    class SpotifyException(Exception):  # type: ignore
        http_status: Optional[int] = None


logger = get_logger(__name__)


class SpotifyClient:
    """High level client around Spotipy with rate limiting and retries."""

    def __init__(
        self,
        config: SpotifyConfig,
        client: Optional[Spotify] = None,
        rate_limit_seconds: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        self._config = config
        self._rate_limit_seconds = rate_limit_seconds
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request_time = 0.0

        if client is not None:
            self._client = client
        else:
            if spotipy is None:
                raise RuntimeError(
                    "spotipy is required for SpotifyClient but is not installed"
                )
            if not (config.client_id and config.client_secret and config.redirect_uri):
                raise ValueError("Spotify configuration is incomplete")

            auth_manager = SpotifyOAuth(
                client_id=config.client_id,
                client_secret=config.client_secret,
                redirect_uri=config.redirect_uri,
                scope=config.scope,
                cache_handler=SettingsCacheHandler(),
            )
            self._client = spotipy.Spotify(auth_manager=auth_manager)

    def _respect_rate_limit(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._rate_limit_seconds:
                time.sleep(self._rate_limit_seconds - elapsed)
            self._last_request_time = time.monotonic()

    def _execute(self, func, *args, **kwargs):
        backoff = 0.5
        for attempt in range(1, self._max_retries + 1):
            self._respect_rate_limit()
            try:
                return func(*args, **kwargs)
            except (
                SpotifyException
            ) as exc:  # pragma: no cover - network errors are mocked in tests
                status = getattr(exc, "http_status", None)
                if status not in {429, 502, 503} or attempt == self._max_retries:
                    logger.error("Spotify API request failed", exc_info=exc)
                    raise
                logger.warning("Retrying Spotify API request due to status %s", status)
                time.sleep(backoff)
                backoff *= 2
            except Exception as exc:  # pragma: no cover
                if attempt == self._max_retries:
                    raise
                logger.warning("Retrying Spotify API request due to %s", exc)
                time.sleep(backoff)
                backoff *= 2

    def is_authenticated(self) -> bool:
        try:
            profile = self._execute(self._client.current_user)
        except Exception:
            return False
        return bool(profile)

    def _build_search_query(
        self,
        query: str,
        *,
        genre: Optional[str] = None,
        year: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> str:
        terms = [query]
        if genre:
            term = f'genre:"{genre}"' if " " in genre else f"genre:{genre}"
            terms.append(term)
        if year is not None:
            terms.append(f"year:{year}")
        elif year_from is not None or year_to is not None:
            if year_from is not None and year_to is not None:
                terms.append(f"year:{year_from}-{year_to}")
            elif year_from is not None:
                terms.append(f"year:{year_from}-")
            elif year_to is not None:
                terms.append(f"year:-{year_to}")
        return " ".join(term for term in terms if term)

    @staticmethod
    def _normalise_text(value: Optional[str]) -> str:
        if not value:
            return ""
        text = re.sub(r"[^\w\s]", " ", str(value).lower())
        return " ".join(text.split())

    @staticmethod
    def _format_query_field(field: str, value: Optional[str]) -> str:
        if not value:
            return ""
        value = str(value).strip()
        if not value:
            return ""
        if " " in value:
            return f'{field}:"{value}"'
        return f"{field}:{value}"

    @staticmethod
    def _extract_artist_names(payload: Any) -> str:
        if not isinstance(payload, list):
            return ""
        names: List[str] = []
        for entry in payload:
            if isinstance(entry, dict):
                name = entry.get("name")
                if name:
                    names.append(str(name))
            elif isinstance(entry, str):
                names.append(entry)
        return ", ".join(names)

    @staticmethod
    def _score_track_candidate(
        candidate: Dict[str, Any],
        *,
        artist: str,
        title: str,
        album: Optional[str],
        duration_ms: Optional[int],
        isrc: Optional[str],
    ) -> float:
        score = 0.0
        target_artist = SpotifyClient._normalise_text(artist)
        target_title = SpotifyClient._normalise_text(title)
        target_album = SpotifyClient._normalise_text(album)

        candidate_title = SpotifyClient._normalise_text(candidate.get("name"))
        candidate_artist = SpotifyClient._normalise_text(
            SpotifyClient._extract_artist_names(candidate.get("artists"))
        )
        candidate_album = ""
        album_payload = candidate.get("album")
        if isinstance(album_payload, dict):
            candidate_album = SpotifyClient._normalise_text(album_payload.get("name"))
        elif isinstance(album_payload, str):
            candidate_album = SpotifyClient._normalise_text(album_payload)

        candidate_isrc = None
        external_ids = candidate.get("external_ids")
        if isinstance(external_ids, dict):
            value = external_ids.get("isrc")
            if value:
                candidate_isrc = str(value).lower()

        if isrc and candidate_isrc and candidate_isrc == isrc.lower():
            score += 120.0

        if target_title and candidate_title:
            if target_title == candidate_title:
                score += 40.0
            elif target_title in candidate_title or candidate_title in target_title:
                score += 12.0

        if target_artist and candidate_artist:
            if target_artist == candidate_artist:
                score += 35.0
            elif target_artist in candidate_artist or candidate_artist in target_artist:
                score += 15.0

        if target_album and candidate_album:
            if target_album == candidate_album:
                score += 10.0
            elif target_album in candidate_album or candidate_album in target_album:
                score += 4.0

        candidate_duration = candidate.get("duration_ms")
        if duration_ms and isinstance(candidate_duration, (int, float)):
            difference = abs(int(candidate_duration) - int(duration_ms))
            if difference <= 2000:
                score += 25.0
            elif difference <= 5000:
                score += 8.0
            else:
                score -= difference / 1000.0

        return score

    def search_tracks(
        self,
        query: str,
        limit: int = 20,
        *,
        genre: Optional[str] = None,
        year: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        search_query = self._build_search_query(
            query, genre=genre, year=year, year_from=year_from, year_to=year_to
        )
        return self._execute(
            self._client.search, q=search_query, type="track", limit=limit
        )

    def search_artists(
        self,
        query: str,
        limit: int = 20,
        *,
        genre: Optional[str] = None,
        year: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        search_query = self._build_search_query(
            query, genre=genre, year=year, year_from=year_from, year_to=year_to
        )
        return self._execute(
            self._client.search, q=search_query, type="artist", limit=limit
        )

    def get_artist(self, artist_id: str) -> Dict[str, Any] | None:
        if not artist_id:
            return None
        return self._execute(self._client.artist, artist_id)

    def search_albums(
        self,
        query: str,
        limit: int = 20,
        *,
        genre: Optional[str] = None,
        year: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        search_query = self._build_search_query(
            query, genre=genre, year=year, year_from=year_from, year_to=year_to
        )
        return self._execute(
            self._client.search, q=search_query, type="album", limit=limit
        )

    def get_user_playlists(self, limit: int = 50) -> Dict[str, Any]:
        return self._execute(self._client.current_user_playlists, limit=limit)

    def get_track_details(self, track_id: str) -> Dict[str, Any]:
        return self._execute(self._client.track, track_id)

    def get_audio_features(self, track_id: str) -> Dict[str, Any]:
        features = self._execute(self._client.audio_features, [track_id]) or []
        return features[0] if features else {}

    def get_multiple_audio_features(self, track_ids: List[str]) -> Dict[str, Any]:
        features = self._execute(self._client.audio_features, track_ids)
        return {"audio_features": features or []}

    def get_playlist_items(
        self, playlist_id: str, limit: int = 100, *, offset: int = 0
    ) -> Dict[str, Any]:
        return self._execute(
            self._client.playlist_items, playlist_id, limit=limit, offset=offset
        )

    def find_track_match(
        self,
        *,
        artist: str,
        title: str,
        album: Optional[str] = None,
        duration_ms: Optional[int] = None,
        isrc: Optional[str] = None,
        limit: int = 20,
    ) -> Optional[Dict[str, Any]]:
        artist = artist or ""
        title = title or ""
        if not artist.strip() or not title.strip():
            return None

        query_parts = [
            self._format_query_field("track", title),
            self._format_query_field("artist", artist),
        ]
        if album:
            query_parts.append(self._format_query_field("album", album))

        query = " ".join(part for part in query_parts if part)
        if not query:
            query = f"{artist} {title}".strip()

        response = self.search_tracks(query, limit=limit)
        tracks_payload = response.get("tracks") if isinstance(response, dict) else None
        items = (
            tracks_payload.get("items") if isinstance(tracks_payload, dict) else None
        )
        if not isinstance(items, list):
            return None

        best_score = float("-inf")
        best_track: Optional[Dict[str, Any]] = None

        for candidate in items:
            if not isinstance(candidate, dict):
                continue
            score = self._score_track_candidate(
                candidate,
                artist=artist,
                title=title,
                album=album,
                duration_ms=duration_ms,
                isrc=isrc,
            )
            if score > best_score:
                best_score = score
                best_track = candidate

        if best_track is None or best_score < 1.0:
            logger.debug(
                "No suitable Spotify track match found", extra={"query": query}
            )
            return None

        return best_track

    def add_tracks_to_playlist(
        self, playlist_id: str, track_uris: List[str]
    ) -> Dict[str, Any]:
        return self._execute(self._client.playlist_add_items, playlist_id, track_uris)

    def get_album_details(self, album_id: str) -> Dict[str, Any]:
        """Return metadata for a single Spotify album."""

        return self._execute(self._client.album, album_id)

    def get_artist_albums(
        self,
        artist_id: str,
        *,
        include_groups: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return the list of albums for a Spotify artist."""

        if not artist_id:
            return []

        albums: List[Dict[str, Any]] = []
        offset = 0
        while True:
            kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
            if include_groups:
                kwargs["include_groups"] = include_groups
            response = self._execute(self._client.artist_albums, artist_id, **kwargs)
            if isinstance(response, dict):
                items = response.get("items")
                if isinstance(items, list):
                    albums.extend(item for item in items if isinstance(item, dict))
                else:
                    items = []
                if not response.get("next") or not items:
                    break
            elif isinstance(response, list):
                albums.extend(item for item in response if isinstance(item, dict))
                if len(response) < limit:
                    break
            else:
                break
            offset += limit
        return albums

    def get_album_tracks(
        self,
        album_id: str,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return all tracks for the given Spotify album."""

        if not album_id:
            return []

        tracks: List[Dict[str, Any]] = []
        offset = 0
        while True:
            response = self._execute(
                self._client.album_tracks,
                album_id,
                limit=limit,
                offset=offset,
            )
            if isinstance(response, dict):
                items = response.get("items")
                if isinstance(items, list):
                    tracks.extend(item for item in items if isinstance(item, dict))
                else:
                    items = []
                if not response.get("next") or not items:
                    break
            elif isinstance(response, list):
                tracks.extend(item for item in response if isinstance(item, dict))
                if len(response) < limit:
                    break
            else:
                break
            offset += limit
        return tracks

    def remove_tracks_from_playlist(
        self, playlist_id: str, track_uris: List[str]
    ) -> Dict[str, Any]:
        return self._execute(
            self._client.playlist_remove_all_occurrences_of_items,
            playlist_id,
            track_uris,
        )

    def reorder_playlist_items(
        self, playlist_id: str, range_start: int, insert_before: int
    ) -> Dict[str, Any]:
        return self._execute(
            self._client.playlist_reorder_items,
            playlist_id,
            range_start=range_start,
            insert_before=insert_before,
        )

    def get_saved_tracks(self, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.current_user_saved_tracks, limit=limit)

    def save_tracks(self, track_ids: List[str]) -> Dict[str, Any]:
        return self._execute(self._client.current_user_saved_tracks_add, track_ids)

    def remove_saved_tracks(self, track_ids: List[str]) -> Dict[str, Any]:
        return self._execute(self._client.current_user_saved_tracks_delete, track_ids)

    def get_current_user(self) -> Dict[str, Any]:
        return self._execute(self._client.current_user)

    def get_top_tracks(self, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.current_user_top_tracks, limit=limit)

    def get_top_artists(self, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.current_user_top_artists, limit=limit)

    def get_recommendations(
        self,
        seed_tracks: Optional[List[str]] = None,
        seed_artists: Optional[List[str]] = None,
        seed_genres: Optional[List[str]] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit}
        if seed_tracks:
            params["seed_tracks"] = seed_tracks
        if seed_artists:
            params["seed_artists"] = seed_artists
        if seed_genres:
            params["seed_genres"] = seed_genres
        return self._execute(self._client.recommendations, **params)

    def get_followed_artists(self, limit: int = 50) -> Dict[str, Any]:
        return self._execute(self._client.current_user_followed_artists, limit=limit)

    def get_artist_releases(self, artist_id: str) -> Dict[str, Any]:
        return self._execute(
            self._client.artist_albums,
            artist_id,
            album_type="album,single,compilation",
        )

    def get_artist_top_tracks(
        self, artist_id: str, *, market: Optional[str] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if market:
            params["market"] = market
        return self._execute(self._client.artist_top_tracks, artist_id, **params)

    def get_album_tracks(  # noqa: F811
        self, album_id: str, *, market: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return all tracks for a Spotify album."""

        limit = 50
        offset = 0
        collected: List[Dict[str, Any]] = []
        last_response: Dict[str, Any] | None = None

        while True:
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            if market:
                params["market"] = market
            response = self._execute(self._client.album_tracks, album_id, **params)
            last_response = response
            items = response.get("items") if isinstance(response, dict) else []
            if not isinstance(items, list):
                items = []
            collected.extend(item for item in items if isinstance(item, dict))
            if len(items) < limit:
                break
            total = response.get("total") if isinstance(response, dict) else None
            offset += limit
            if total is not None and offset >= int(total):
                break

        total_tracks = (
            last_response.get("total")
            if isinstance(last_response, dict) and "total" in last_response
            else len(collected)
        )
        return {"items": collected, "total": total_tracks}

    def get_artist_discography(self, artist_id: str) -> Dict[str, Any]:
        """Fetch the complete discography for an artist including tracks."""

        limit = 50
        offset = 0
        albums: List[Dict[str, Any]] = []
        seen_album_ids: set[str] = set()

        while True:
            response = self._execute(
                self._client.artist_albums,
                artist_id,
                album_type="album,single,compilation",
                limit=limit,
                offset=offset,
            )
            items = response.get("items") if isinstance(response, dict) else []
            if not isinstance(items, list):
                items = []
            for album in items:
                if not isinstance(album, dict):
                    continue
                album_id = album.get("id")
                if not album_id or album_id in seen_album_ids:
                    continue
                seen_album_ids.add(album_id)
                tracks_response = self.get_album_tracks(str(album_id))
                albums.append(
                    {"album": album, "tracks": tracks_response.get("items", [])}
                )
            if len(items) < limit:
                break
            total = response.get("total") if isinstance(response, dict) else None
            offset += limit
            if total is not None and offset >= int(total):
                break

        return {"artist_id": artist_id, "albums": albums}

    def get_track_metadata(self, track_id: str) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        if not track_id:
            return metadata

        try:
            track = self._execute(self._client.track, track_id)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Spotify track lookup failed for %s: %s", track_id, exc)
            return metadata

        if not isinstance(track, dict):
            return metadata

        external_ids = track.get("external_ids") or {}
        isrc = external_ids.get("isrc")
        if isrc:
            metadata["isrc"] = str(isrc)

        album = track.get("album") or {}
        album_id = album.get("id")
        album_data: Dict[str, Any] | None = None
        if album_id:
            try:
                album_data = self._execute(self._client.album, album_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Spotify album lookup failed for %s: %s", album_id, exc)

        genres: list[str] = []
        if album_data:
            payload = album_data.get("genres")
            if isinstance(payload, list):
                genres = [str(item) for item in payload if item]

        if not genres:
            artists = track.get("artists")
            if isinstance(artists, list):
                for artist in artists:
                    artist_id = artist.get("id") if isinstance(artist, dict) else None
                    if not artist_id:
                        continue
                    try:
                        artist_payload = self._execute(self._client.artist, artist_id)
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.debug(
                            "Spotify artist lookup failed for %s: %s", artist_id, exc
                        )
                        continue
                    artist_genres = (
                        artist_payload.get("genres")
                        if isinstance(artist_payload, dict)
                        else None
                    )
                    if isinstance(artist_genres, list) and artist_genres:
                        genres = [str(item) for item in artist_genres if item]
                        if genres:
                            break

        if genres:
            metadata["genre"] = genres[0]

        artwork_url = self._pick_best_image(album.get("images"))
        if not artwork_url and album_data is not None:
            artwork_url = self._pick_best_image(album_data.get("images"))
        if artwork_url:
            metadata["artwork_url"] = artwork_url

        copyrights = album.get("copyrights")
        if not copyrights and album_data is not None:
            copyrights = album_data.get("copyrights")
        text = self._extract_copyright(copyrights)
        if text:
            metadata["copyright"] = text

        return metadata

    @staticmethod
    def _pick_best_image(images: Any) -> Optional[str]:
        if not isinstance(images, list):
            return None
        best_url: Optional[str] = None
        best_score = -1
        for item in images:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            width = item.get("width") or 0
            height = item.get("height") or 0
            score = int(width) * int(height)
            if score > best_score:
                best_score = score
                best_url = str(url)
        return best_url

    @staticmethod
    def _extract_copyright(payload: Any) -> Optional[str]:
        if isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict):
                    text = entry.get("text") or entry.get("copyright")
                    if text:
                        return str(text)
                elif isinstance(entry, str) and entry:
                    return entry
        elif isinstance(payload, dict):
            text = payload.get("text") or payload.get("copyright")
            if text:
                return str(text)
        elif isinstance(payload, str) and payload:
            return payload
        return None
