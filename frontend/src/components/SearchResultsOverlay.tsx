import type {
  SpotifyAlbumSearchResult,
  SpotifyArtistSearchResult,
  SpotifySearchResults,
  SpotifyTrackSearchResult
} from '../api/services/spotify';
import { cn } from '../lib/utils';

const formatDuration = (value: number | null): string | null => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  const totalSeconds = Math.round(value / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
};

const formatFollowers = (value: number | null): string | null => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return null;
  }
  return new Intl.NumberFormat().format(value);
};

const trackSubtitle = (track: SpotifyTrackSearchResult): string | null => {
  const parts: string[] = [];
  if (track.artists.length > 0) {
    parts.push(track.artists.join(', '));
  }
  if (track.album) {
    parts.push(track.album);
  }
  const duration = formatDuration(track.durationMs);
  if (duration) {
    parts.push(duration);
  }
  return parts.length > 0 ? parts.join(' • ') : null;
};

const artistSubtitle = (artist: SpotifyArtistSearchResult): string | null => {
  const parts: string[] = [];
  const followers = formatFollowers(artist.followers);
  if (followers) {
    parts.push(`${followers} followers`);
  }
  if (artist.genres.length > 0) {
    parts.push(artist.genres.slice(0, 3).join(', '));
  }
  return parts.length > 0 ? parts.join(' • ') : null;
};

const albumSubtitle = (album: SpotifyAlbumSearchResult): string | null => {
  const parts: string[] = [];
  if (album.artists.length > 0) {
    parts.push(album.artists.join(', '));
  }
  if (album.releaseDate) {
    parts.push(album.releaseDate);
  }
  return parts.length > 0 ? parts.join(' • ') : null;
};

type SearchResultSelection =
  | { type: 'track'; item: SpotifyTrackSearchResult }
  | { type: 'artist'; item: SpotifyArtistSearchResult }
  | { type: 'album'; item: SpotifyAlbumSearchResult };

export interface SearchResultsOverlayProps {
  query: string;
  isOpen: boolean;
  isLoading: boolean;
  error?: string | null;
  results: SpotifySearchResults | null;
  onSelect?: (selection: SearchResultSelection) => void;
  onClose?: () => void;
}

export const SearchResultsOverlay = ({
  query,
  isOpen,
  isLoading,
  error,
  results,
  onSelect,
  onClose
}: SearchResultsOverlayProps) => {
  const shouldRender = isOpen || isLoading || Boolean(error);
  if (!shouldRender) {
    return null;
  }

  const groups: Array<{
    key: 'tracks' | 'artists' | 'albums';
    label: string;
    items: SpotifyTrackSearchResult[] | SpotifyArtistSearchResult[] | SpotifyAlbumSearchResult[];
  }> = [
    { key: 'tracks', label: 'Tracks', items: results?.tracks ?? [] },
    { key: 'artists', label: 'Artists', items: results?.artists ?? [] },
    { key: 'albums', label: 'Albums', items: results?.albums ?? [] }
  ];

  const hasResults = groups.some((group) => group.items.length > 0);

  return (
    <div
      className={cn(
        'absolute left-0 right-0 top-full z-50 mt-2 w-full rounded-lg border border-slate-200 bg-white shadow-xl',
        'focus:outline-none dark:border-slate-700 dark:bg-slate-900'
      )}
      role="region"
      aria-label={query ? `Search results for “${query}”` : 'Search results'}
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          onClose?.();
        }
      }}
    >
      {isLoading ? (
        <p className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400" role="status" aria-live="polite">
          Searching…
        </p>
      ) : error ? (
        <p className="px-4 py-3 text-sm text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
      ) : hasResults ? (
        <div className="max-h-80 overflow-y-auto py-2">
          {groups.map((group) => {
            if (group.items.length === 0) {
              return null;
            }
            return (
              <section key={group.key} aria-label={`${group.label} results`} className="py-1">
                <h3 className="px-4 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  {group.label}
                </h3>
                <ul className="mt-1 space-y-1 px-2" role="listbox">
                  {group.items.map((item) => {
                    let selection: SearchResultSelection;
                    let subtitle: string | null = null;
                    const title = item.name;

                    if (group.key === 'tracks') {
                      const track = item as SpotifyTrackSearchResult;
                      selection = { type: 'track', item: track };
                      subtitle = trackSubtitle(track);
                    } else if (group.key === 'artists') {
                      const artist = item as SpotifyArtistSearchResult;
                      selection = { type: 'artist', item: artist };
                      subtitle = artistSubtitle(artist);
                    } else {
                      const album = item as SpotifyAlbumSearchResult;
                      selection = { type: 'album', item: album };
                      subtitle = albumSubtitle(album);
                    }
                    return (
                      <li key={`${group.key}-${item.id ?? title}`} className="list-none">
                        <button
                          type="button"
                          role="option"
                          onClick={() => {
                            onSelect?.(selection);
                            onClose?.();
                          }}
                          className={cn(
                            'w-full rounded-md px-3 py-2 text-left text-sm transition-colors',
                            'hover:bg-indigo-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500',
                            'dark:hover:bg-slate-800'
                          )}
                        >
                          <span className="block font-medium text-slate-900 dark:text-slate-100">{title}</span>
                          {subtitle ? (
                            <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">{subtitle}</span>
                          ) : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>
      ) : (
        <p className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400" role="status" aria-live="polite">
          No results found{query ? ` for “${query}”` : ''}.
        </p>
      )}
    </div>
  );
};

export type { SearchResultSelection };

export default SearchResultsOverlay;
