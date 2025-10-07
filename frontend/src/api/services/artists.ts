import { apiUrl, request } from '../client';
import type {
  ArtistActivityEntry,
  ArtistDetailResponse,
  ArtistListResponse,
  ArtistMatch,
  ArtistMatchBadge,
  ArtistMatchStatus,
  ArtistPriority,
  ArtistQueueStatus,
  ArtistRelease,
  ArtistSummary,
  ArtistWatchlistSettings,
  WatchlistArtistPayload
} from '../types';

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');

const asNullableString = (value: unknown): string | null => {
  if (value === undefined || value === null) {
    return null;
  }
  const str = asString(value);
  return str.length > 0 ? str : null;
};

const asNumber = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const parsePriority = (value: unknown): ArtistPriority => {
  if (value === 'low' || value === 'medium' || value === 'high') {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    return value as ArtistPriority;
  }
  return 'medium';
};

const parseWatchlistSettings = (value: unknown): ArtistWatchlistSettings | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const enabled = typeof record.enabled === 'boolean' ? record.enabled : true;
  const priority = parsePriority(record.priority);
  const interval = asNumber(record.interval_days);
  return {
    id: asNullableString(record.id ?? record.watchlist_id),
    enabled,
    priority,
    interval_days: interval,
    last_synced_at: asNullableString(record.last_synced_at),
    next_sync_at: asNullableString(record.next_sync_at)
  };
};

const parseExternalIds = (value: unknown): Record<string, string> | undefined => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return undefined;
  }
  return Object.entries(value).reduce<Record<string, string>>((acc, [key, val]) => {
    const normalized = asString(val);
    if (normalized) {
      acc[key] = normalized;
    }
    return acc;
  }, {});
};

const parseArtistSummary = (value: unknown): ArtistSummary | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const id = asString(record.id ?? record.artist_id);
  const name = asString(record.name ?? record.artist_name);
  if (!id || !name) {
    return null;
  }
  return {
    id,
    name,
    image_url: asNullableString(record.image_url ?? record.image),
    external_ids: parseExternalIds(record.external_ids ?? record.ids),
    watchlist: parseWatchlistSettings(record.watchlist ?? record.watchlist_settings),
    health_status: asNullableString(record.health_status ?? record.status ?? record.health),
    releases_total: asNumber(record.releases_total ?? record.release_count),
    matches_pending: asNumber(record.matches_pending ?? record.pending_matches),
    updated_at: asNullableString(record.updated_at ?? record.synced_at ?? record.modified_at)
  };
};

const parseRelease = (value: unknown): ArtistRelease | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const id = asString(record.id ?? record.release_id);
  const title = asString(record.title ?? record.name);
  if (!id || !title) {
    return null;
  }
  return {
    id,
    title,
    type: asNullableString(record.type ?? record.category),
    released_at: asNullableString(record.released_at ?? record.release_date),
    spotify_url: asNullableString(record.spotify_url ?? record.url),
    metadata: typeof record.metadata === 'object' && record.metadata !== null ? (record.metadata as Record<string, unknown>) :
    undefined
  };
};

const parseMatchStatus = (value: unknown): ArtistMatchStatus => {
  if (value === 'pending' || value === 'accepted' || value === 'rejected') {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    return value as ArtistMatchStatus;
  }
  return 'pending';
};

const parseMatchBadges = (value: unknown): ArtistMatchBadge[] | undefined => {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const normalized = value
    .map((entry) => {
      if (!entry || typeof entry !== 'object') {
        return null;
      }
      const record = entry as Record<string, unknown>;
      const label = asString(record.label ?? record.text);
      if (!label) {
        return null;
      }
      const tone = asString(record.tone ?? record.variant);
      return {
        label,
        tone: tone === '' ? undefined : (tone as ArtistMatchBadge['tone'])
      };
    })
    .filter((badge): badge is NonNullable<typeof badge> => badge !== null);
  return normalized.length ? normalized : undefined;
};

const parseMatch = (value: unknown): ArtistMatch | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const id = asString(record.id ?? record.match_id);
  const title = asString(record.title ?? record.track ?? record.release_title);
  if (!id || !title) {
    return null;
  }
  return {
    id,
    title,
    confidence: asNumber(record.confidence),
    release_title: asNullableString(record.release_title ?? record.release),
    provider: asNullableString(record.provider ?? record.source),
    status: parseMatchStatus(record.status),
    badges: parseMatchBadges(record.badges),
    submitted_at: asNullableString(record.submitted_at ?? record.created_at)
  };
};

const parseActivity = (value: unknown): ArtistActivityEntry | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const id = asString(record.id ?? record.activity_id ?? record.created_at ?? Math.random().toString(16));
  const message = asString(record.message ?? record.summary ?? record.description);
  const createdAt = asString(record.created_at ?? record.timestamp ?? record.time);
  if (!message || !createdAt) {
    return null;
  }
  return {
    id,
    created_at: createdAt,
    message,
    category: asNullableString(record.category ?? record.type),
    meta:
      typeof record.meta === 'object' && record.meta !== null
        ? (record.meta as Record<string, unknown>)
        : undefined
  };
};

const parseQueueStatus = (value: unknown): ArtistQueueStatus | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  return {
    job_id: asNullableString(record.job_id ?? record.id),
    status: asNullableString(record.status),
    attempts: asNumber(record.attempts),
    eta: asNullableString(record.eta ?? record.next_run_at),
    queued_at: asNullableString(record.queued_at),
    started_at: asNullableString(record.started_at),
    updated_at: asNullableString(record.updated_at)
  };
};

const normalizeListResponse = (value: unknown): ArtistListResponse => {
  const itemsSource =
    value && typeof value === 'object' && !Array.isArray(value)
      ? (value as { items?: unknown[]; results?: unknown[]; total?: unknown; page?: unknown; per_page?: unknown })
      : undefined;
  const itemsRaw =
    Array.isArray(value)
      ? value
      : Array.isArray(itemsSource?.items)
        ? itemsSource?.items
        : Array.isArray(itemsSource?.results)
          ? itemsSource?.results
          : [];

  const items = itemsRaw
    .map((entry) => parseArtistSummary(entry))
    .filter((entry): entry is ArtistSummary => entry !== null);

  return {
    items,
    total: asNumber(itemsSource?.total) ?? items.length,
    page: asNumber(itemsSource?.page) ?? 1,
    per_page: asNumber(itemsSource?.per_page ?? (itemsSource as { perPage?: unknown })?.perPage) ?? items.length || 1
  };
};

const normalizeDetailResponse = (value: unknown): ArtistDetailResponse => {
  const container = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  const artist = parseArtistSummary(container.artist ?? value) ?? {
    id: 'unknown',
    name: 'Unbekannter Artist',
    watchlist: null
  };
  const releasesSource = Array.isArray(container.releases)
    ? container.releases
    : Array.isArray((container.releases as { items?: unknown[] } | undefined)?.items)
      ? ((container.releases as { items?: unknown[] }).items as unknown[])
      : [];
  const matchesSource = Array.isArray(container.matches)
    ? container.matches
    : Array.isArray((container.matches as { items?: unknown[] } | undefined)?.items)
      ? ((container.matches as { items?: unknown[] }).items as unknown[])
      : [];
  const activitySource = Array.isArray(container.activity)
    ? container.activity
    : Array.isArray((container.activity as { items?: unknown[] } | undefined)?.items)
      ? ((container.activity as { items?: unknown[] }).items as unknown[])
      : [];

  return {
    artist,
    releases: releasesSource
      .map((entry) => parseRelease(entry))
      .filter((entry): entry is ArtistRelease => entry !== null),
    matches: matchesSource
      .map((entry) => parseMatch(entry))
      .filter((entry): entry is ArtistMatch => entry !== null),
    activity: activitySource
      .map((entry) => parseActivity(entry))
      .filter((entry): entry is ArtistActivityEntry => entry !== null),
    queue: parseQueueStatus(container.queue ?? container.sync)
  };
};

export interface ListArtistsParams {
  search?: string;
  priority?: ArtistPriority | 'all';
  health?: string | 'all';
  page?: number;
  perPage?: number;
  watchlistOnly?: boolean;
}

const serializeListParams = (params: ListArtistsParams = {}) => {
  const result: Record<string, unknown> = {};
  if (params.search) {
    result.search = params.search;
  }
  if (params.priority && params.priority !== 'all') {
    result.priority = params.priority;
  }
  if (params.health && params.health !== 'all') {
    result.health = params.health;
  }
  if (typeof params.page === 'number') {
    result.page = params.page;
  }
  if (typeof params.perPage === 'number') {
    result.per_page = params.perPage;
  }
  if (params.watchlistOnly) {
    result.watchlist = true;
  }
  return result;
};

export const listArtists = async (params: ListArtistsParams = {}): Promise<ArtistListResponse> => {
  const payload = await request<unknown>({
    method: 'GET',
    url: apiUrl('/api/v1/artists'),
    params: serializeListParams(params)
  });
  return normalizeListResponse(payload);
};

export const getArtistDetail = async (artistId: string): Promise<ArtistDetailResponse> => {
  const payload = await request<unknown>({
    method: 'GET',
    url: apiUrl(`/api/v1/artists/${encodeURIComponent(artistId)}`)
  });
  return normalizeDetailResponse(payload);
};

export interface UpdateWatchlistPayload {
  enabled?: boolean;
  priority?: ArtistPriority;
  interval_days?: number | null;
}

export const updateWatchlistEntry = async (
  watchlistId: string,
  payload: UpdateWatchlistPayload
): Promise<ArtistWatchlistSettings | null> => {
  const response = await request<unknown>({
    method: 'PATCH',
    url: apiUrl(`/api/v1/watchlist/${encodeURIComponent(watchlistId)}`),
    data: payload
  });
  return parseWatchlistSettings(response);
};

export const addArtistToWatchlist = async (
  payload: WatchlistArtistPayload
): Promise<ArtistSummary | null> => {
  const response = await request<unknown>({
    method: 'POST',
    url: apiUrl('/api/v1/watchlist'),
    data: payload
  });
  if (response && typeof response === 'object' && !Array.isArray(response) && 'artist' in (response as object)) {
    const candidate = (response as { artist?: unknown }).artist;
    const summary = parseArtistSummary(candidate);
    if (summary) {
      return summary;
    }
  }
  return parseArtistSummary(response);
};

export const removeWatchlistEntry = async (watchlistId: string): Promise<void> => {
  await request<void>({
    method: 'DELETE',
    url: apiUrl(`/api/v1/watchlist/${encodeURIComponent(watchlistId)}`),
    responseType: 'void'
  });
};

export const enqueueArtistResync = async (artistId: string): Promise<void> => {
  await request<void>({
    method: 'POST',
    url: apiUrl(`/api/v1/artists/${encodeURIComponent(artistId)}:resync`),
    responseType: 'void'
  });
};

export const invalidateArtistCache = async (artistId: string): Promise<void> => {
  await request<void>({
    method: 'POST',
    url: apiUrl(`/api/v1/artists/${encodeURIComponent(artistId)}:invalidate`),
    responseType: 'void'
  });
};

export type ArtistMatchAction = 'accept' | 'reject';

export const updateArtistMatchStatus = async (
  artistId: string,
  matchId: string,
  action: ArtistMatchAction
): Promise<void> => {
  await request<void>({
    method: 'POST',
    url: apiUrl(`/api/v1/artists/${encodeURIComponent(artistId)}/matches/${encodeURIComponent(matchId)}:${action}`),
    responseType: 'void'
  });
};

export type {
  ArtistSummary,
  ArtistRelease,
  ArtistMatch,
  ArtistActivityEntry,
  ArtistQueueStatus
};
