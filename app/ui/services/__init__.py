"""UI service layer wrapping backend operations for fragments and forms."""

from .activity import ActivityPage, ActivityUiService, get_activity_ui_service
from .downloads import DownloadPage, DownloadRow, DownloadsUiService, get_downloads_ui_service
from .jobs import JobsUiService, OrchestratorJob, get_jobs_ui_service
from .search import (
    SearchResult,
    SearchResultsPage,
    SearchUiService,
    get_search_ui_service,
)
from .spotify import (
    SpotifyBackfillSnapshot,
    SpotifyManualResult,
    SpotifyOAuthHealth,
    SpotifyPlaylistRow,
    SpotifyStatus,
    SpotifyUiService,
    get_spotify_ui_service,
)
from .watchlist import (
    WatchlistRow,
    WatchlistTable,
    WatchlistUiService,
    get_watchlist_ui_service,
)

__all__ = [
    "ActivityPage",
    "ActivityUiService",
    "get_activity_ui_service",
    "DownloadPage",
    "DownloadRow",
    "DownloadsUiService",
    "get_downloads_ui_service",
    "JobsUiService",
    "OrchestratorJob",
    "get_jobs_ui_service",
    "SearchResult",
    "SearchResultsPage",
    "SearchUiService",
    "get_search_ui_service",
    "SpotifyBackfillSnapshot",
    "SpotifyManualResult",
    "SpotifyOAuthHealth",
    "SpotifyPlaylistRow",
    "SpotifyStatus",
    "SpotifyUiService",
    "get_spotify_ui_service",
    "WatchlistRow",
    "WatchlistTable",
    "WatchlistUiService",
    "get_watchlist_ui_service",
]
