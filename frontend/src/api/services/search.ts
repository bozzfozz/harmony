import { apiUrl, request } from '../client';
import type { WatchlistArtistEntry, WatchlistArtistPayload } from '../types';

const normalizeWatchlistEntry = (entry: unknown): WatchlistArtistEntry | null => {
  if (!entry || typeof entry !== 'object') {
    return null;
  }
  const record = entry as Record<string, unknown>;
  if (record.id === undefined) {
    return null;
  }
  const id = record.id as number | string;
  const spotifyId = typeof record.spotify_artist_id === 'string' ? record.spotify_artist_id : '';
  const name = typeof record.name === 'string' ? record.name : '';
  const lastChecked =
    typeof record.last_checked === 'string' && record.last_checked.trim().length > 0
      ? record.last_checked
      : null;
  const createdAt = typeof record.created_at === 'string' ? record.created_at : '';
  if (!spotifyId || !name) {
    return null;
  }
  return {
    id,
    spotify_artist_id: spotifyId,
    name,
    last_checked: lastChecked,
    created_at: createdAt
  };
};

const extractWatchlistEntries = (payload: unknown): WatchlistArtistEntry[] => {
  const items = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { items?: unknown[] }).items)
      ? (payload as { items: unknown[] }).items
      : [];
  return items
    .map(normalizeWatchlistEntry)
    .filter((entry): entry is WatchlistArtistEntry => entry !== null);
};

export const getWatchlist = async (): Promise<WatchlistArtistEntry[]> => {
  const payload = await request<unknown>({ method: 'GET', url: apiUrl('/watchlist') });
  return extractWatchlistEntries(payload);
};

export const addWatchlistArtist = async (
  payload: WatchlistArtistPayload
): Promise<WatchlistArtistEntry> => {
  const response = await request<unknown>({ method: 'POST', url: apiUrl('/watchlist'), data: payload });
  return (
    normalizeWatchlistEntry(response) ?? {
      id: 0,
      spotify_artist_id: payload.spotify_artist_id,
      name: payload.name,
      last_checked: null,
      created_at: ''
    }
  );
};

export const removeWatchlistArtist = async (artistId: number | string) =>
  request<void>({ method: 'DELETE', url: apiUrl(`/watchlist/${artistId}`), responseType: 'void' });

export type { WatchlistArtistEntry, WatchlistArtistPayload };
