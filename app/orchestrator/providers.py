"""Factories wiring orchestrator handler dependencies."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.config import WatchlistWorkerConfig
from app.core.matching_engine import MusicMatchingEngine
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.dependencies import (
    get_app_config,
    get_matching_engine,
    get_soulseek_client,
    get_spotify_client,
)
from app.orchestrator.handlers import (
    ArtistDeltaHandlerDeps,
    ArtistRefreshHandlerDeps,
    ArtworkService,
    MatchingHandlerDeps,
    LyricsService,
    MetadataService,
    RetryHandlerDeps,
    SyncHandlerDeps,
    SyncJobSubmitter,
    WatchlistHandlerDeps,
)


def build_sync_handler_deps(
    *,
    soulseek_client: SoulseekClient | None = None,
    metadata_service: MetadataService | None = None,
    artwork_service: ArtworkService | None = None,
    lyrics_service: LyricsService | None = None,
    session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
) -> SyncHandlerDeps:
    """Construct orchestrator sync handler dependencies using configured clients."""

    client = soulseek_client or get_soulseek_client()
    kwargs: dict[str, object] = {}
    if session_factory is not None:
        kwargs["session_factory"] = session_factory
    return SyncHandlerDeps(
        soulseek_client=client,
        metadata_service=metadata_service,
        artwork_service=artwork_service,
        lyrics_service=lyrics_service,
        **kwargs,
    )


def build_matching_handler_deps(
    *,
    engine: MusicMatchingEngine | None = None,
    session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
) -> MatchingHandlerDeps:
    """Return matching handler dependencies bound to the configured engine."""

    resolved_engine = engine or get_matching_engine()
    kwargs: dict[str, object] = {}
    if session_factory is not None:
        kwargs["session_factory"] = session_factory
    return MatchingHandlerDeps(engine=resolved_engine, **kwargs)


def build_retry_handler_deps(
    *,
    submit_sync_job: SyncJobSubmitter | None = None,
    session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
) -> RetryHandlerDeps:
    """Create retry handler dependencies with optional overrides."""

    kwargs: dict[str, object] = {}
    if submit_sync_job is not None:
        kwargs["submit_sync_job"] = submit_sync_job
    if session_factory is not None:
        kwargs["session_factory"] = session_factory
    return RetryHandlerDeps(**kwargs)


def build_watchlist_handler_deps(
    *,
    spotify_client: SpotifyClient | None = None,
    soulseek_client: SoulseekClient | None = None,
    config: WatchlistWorkerConfig | None = None,
    submit_sync_job: SyncJobSubmitter | None = None,
) -> WatchlistHandlerDeps:
    """Return watchlist handler dependencies bound to configured services."""

    resolved_config = config or get_app_config().watchlist
    kwargs: dict[str, object] = {}
    if submit_sync_job is not None:
        kwargs["submit_sync_job"] = submit_sync_job
    return WatchlistHandlerDeps(
        spotify_client=spotify_client or get_spotify_client(),
        soulseek_client=soulseek_client or get_soulseek_client(),
        config=resolved_config,
        **kwargs,
    )


def build_artist_refresh_handler_deps(
    *,
    config: WatchlistWorkerConfig | None = None,
    submit_delta_job: SyncJobSubmitter | None = None,
) -> ArtistRefreshHandlerDeps:
    """Construct handler dependencies for artist refresh jobs."""

    resolved_config = config or get_app_config().watchlist
    kwargs: dict[str, object] = {}
    if submit_delta_job is not None:
        kwargs["submit_delta_job"] = submit_delta_job
    return ArtistRefreshHandlerDeps(config=resolved_config, **kwargs)


def build_artist_delta_handler_deps(
    *,
    spotify_client: SpotifyClient | None = None,
    soulseek_client: SoulseekClient | None = None,
    config: WatchlistWorkerConfig | None = None,
    submit_sync_job: SyncJobSubmitter | None = None,
) -> ArtistDeltaHandlerDeps:
    """Construct handler dependencies for artist delta jobs."""

    resolved_config = config or get_app_config().watchlist
    kwargs: dict[str, object] = {}
    if submit_sync_job is not None:
        kwargs["submit_sync_job"] = submit_sync_job
    return ArtistDeltaHandlerDeps(
        spotify_client=spotify_client or get_spotify_client(),
        soulseek_client=soulseek_client or get_soulseek_client(),
        config=resolved_config,
        **kwargs,
    )


__all__ = [
    "build_sync_handler_deps",
    "build_matching_handler_deps",
    "build_retry_handler_deps",
    "build_watchlist_handler_deps",
    "build_artist_refresh_handler_deps",
    "build_artist_delta_handler_deps",
]
