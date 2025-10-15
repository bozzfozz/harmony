"""UI service layer wrapping backend operations for fragments and forms."""

from .downloads import DownloadPage, DownloadRow, DownloadsUiService, get_downloads_ui_service
from .jobs import JobsUiService, OrchestratorJob
from .search import (
    SearchResult,
    SearchResultsPage,
    SearchUiService,
    get_search_ui_service,
)
from .watchlist import (
    WatchlistRow,
    WatchlistTable,
    WatchlistUiService,
    get_watchlist_ui_service,
)

__all__ = [
    "DownloadPage",
    "DownloadRow",
    "DownloadsUiService",
    "get_downloads_ui_service",
    "JobsUiService",
    "OrchestratorJob",
    "SearchResult",
    "SearchResultsPage",
    "SearchUiService",
    "get_search_ui_service",
    "WatchlistRow",
    "WatchlistTable",
    "WatchlistUiService",
    "get_watchlist_ui_service",
]
