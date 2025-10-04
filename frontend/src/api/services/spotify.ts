import { apiUrl, request } from '../client';
import type {
  ArtistPreferenceEntry,
  ArtistPreferencesResponse,
  ArtistReleasesResponse,
  FollowedArtistsResponse,
  NormalizedTrack,
  SpotifyAlbumSearchResult,
  SpotifyArtist,
  SpotifyArtistSearchResult,
  SpotifyArtistRelease,
  SpotifyFreeEnqueuePayload,
  SpotifyFreeEnqueueResponse,
  SpotifyFreeParsePayload,
  SpotifyFreeParseResponse,
  SpotifyImage,
  SpotifyProOAuthProfile,
  SpotifyProOAuthStartResponse,
  SpotifyProOAuthStatus,
  SpotifyProOAuthStatusResponse,
  SpotifyStatusResponse,
  SpotifyRawAlbum,
  SpotifyRawArtist,
  SpotifyRawTrack,
  SpotifySearchResponse,
  SpotifySearchResults,
  SpotifyTrackSearchResult
} from '../types';

const notEmpty = <T>(value: T | null | undefined): value is T => value !== null && value !== undefined;

const ensureString = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

const toNullableString = (value: unknown): string | null => ensureString(value);

const getSessionStorage = (): Storage | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch (error) {
    console.warn('Unable to access sessionStorage', error);
    return null;
  }
};

const OAUTH_STATE_STORAGE_KEY = 'harmony.spotify.pro.oauth.state';

export const createSpotifyProOAuthState = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const randomPart = Math.random().toString(36).slice(2, 10);
  return `spotify_oauth_${randomPart}${Date.now().toString(36)}`;
};

export const rememberSpotifyProOAuthState = (state: string) => {
  const storage = getSessionStorage();
  if (!storage) {
    return;
  }
  try {
    storage.setItem(OAUTH_STATE_STORAGE_KEY, state);
  } catch (error) {
    console.warn('Unable to persist Spotify OAuth state', error);
  }
};

export const getStoredSpotifyProOAuthState = (): string | null => {
  const storage = getSessionStorage();
  if (!storage) {
    return null;
  }
  try {
    return storage.getItem(OAUTH_STATE_STORAGE_KEY);
  } catch (error) {
    console.warn('Unable to read Spotify OAuth state from storage', error);
    return null;
  }
};

export const clearSpotifyProOAuthState = () => {
  const storage = getSessionStorage();
  if (!storage) {
    return;
  }
  try {
    storage.removeItem(OAUTH_STATE_STORAGE_KEY);
  } catch (error) {
    console.warn('Unable to clear Spotify OAuth state from storage', error);
  }
};

export const consumeSpotifyProOAuthState = (state: string | null | undefined): boolean => {
  const storage = getSessionStorage();
  if (!storage) {
    return false;
  }
  try {
    const stored = storage.getItem(OAUTH_STATE_STORAGE_KEY);
    if (stored && state && stored === state) {
      storage.removeItem(OAUTH_STATE_STORAGE_KEY);
      return true;
    }
    if (!state) {
      storage.removeItem(OAUTH_STATE_STORAGE_KEY);
    }
    return stored !== null && stored === state;
  } catch (error) {
    console.warn('Unable to consume Spotify OAuth state from storage', error);
    return false;
  }
};

const normalizeSpotifyProOAuthStatus = (value: unknown): SpotifyProOAuthStatus => {
  if (typeof value !== 'string') {
    return 'pending';
  }
  const normalized = value.trim().toLowerCase();
  if (['authorized', 'authorised', 'success', 'succeeded', 'completed', 'ok'].includes(normalized)) {
    return 'authorized';
  }
  if (['failed', 'failure', 'error'].includes(normalized)) {
    return 'failed';
  }
  if (['cancelled', 'canceled', 'aborted', 'closed'].includes(normalized)) {
    return 'cancelled';
  }
  return 'pending';
};

const normalizeSpotifyProOAuthProfile = (value: unknown): SpotifyProOAuthProfile | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const profile: SpotifyProOAuthProfile = {};
  const id = toNullableString(record.id);
  if (id) {
    profile.id = id;
  }
  const displayName = toNullableString(record.display_name ?? record.displayName ?? record.name);
  if (displayName) {
    profile.display_name = displayName;
  }
  const email = toNullableString(record.email);
  if (email) {
    profile.email = email;
  }
  const country = toNullableString(record.country);
  if (country) {
    profile.country = country;
  }
  const product = toNullableString(record.product);
  if (product) {
    profile.product = product;
  }
  const uri = toNullableString(record.uri);
  if (uri) {
    profile.uri = uri;
  }
  const href = toNullableString(record.href);
  if (href) {
    profile.href = href;
  }
  return Object.keys(profile).length > 0 ? profile : null;
};

const normalizeSpotifyProOAuthStartResponse = (
  payload: unknown,
  fallbackState: string
): SpotifyProOAuthStartResponse => {
  const record = (payload && typeof payload === 'object') ? (payload as Record<string, unknown>) : {};
  const url =
    toNullableString(record.authorization_url) ??
    toNullableString(record.authorize_url) ??
    toNullableString(record.url) ??
    toNullableString(record.href);
  if (!url) {
    throw new Error('Spotify OAuth start response did not contain an authorization URL');
  }
  const responseState = toNullableString(record.state) ?? fallbackState;
  const expiresAt =
    toNullableString(record.expires_at) ??
    toNullableString(record.expiry) ??
    toNullableString(record.expires) ??
    null;
  return {
    authorization_url: url,
    state: responseState,
    expires_at: expiresAt
  };
};

const normalizeSpotifyProOAuthStatusResponse = (
  payload: unknown,
  fallbackState: string
): SpotifyProOAuthStatusResponse => {
  const record = (payload && typeof payload === 'object') ? (payload as Record<string, unknown>) : {};
  const state = toNullableString(record.state) ?? fallbackState;
  const statusValue = normalizeSpotifyProOAuthStatus(record.status ?? record.state ?? record.result);
  const authenticated =
    typeof record.authenticated === 'boolean'
      ? record.authenticated
      : Boolean(record.success ?? (statusValue === 'authorized'));
  const error =
    toNullableString(record.error) ??
    toNullableString(record.error_description) ??
    toNullableString(record.message) ??
    undefined;
  const completedAt =
    toNullableString(record.completed_at) ??
    toNullableString(record.finished_at) ??
    toNullableString(record.updated_at) ??
    null;
  const profile = normalizeSpotifyProOAuthProfile(record.profile ?? record.user ?? record.account);
  return {
    status: statusValue,
    state,
    authenticated,
    error,
    completed_at: completedAt,
    profile
  };
};

export interface SpotifyProOAuthStartOptions {
  state?: string;
  prompt?: string;
}

export const startSpotifyProOAuth = async (
  options: SpotifyProOAuthStartOptions = {}
): Promise<SpotifyProOAuthStartResponse> => {
  const requestedState = options.state ?? createSpotifyProOAuthState();
  const data: Record<string, unknown> = { state: requestedState };
  if (options.prompt) {
    data.prompt = options.prompt;
  }
  const response = await request<unknown>({
    method: 'POST',
    url: apiUrl('/spotify/pro/oauth/start'),
    data
  });
  const normalized = normalizeSpotifyProOAuthStartResponse(response, requestedState);
  rememberSpotifyProOAuthState(normalized.state);
  return normalized;
};

export const getSpotifyProOAuthStatus = async (
  state: string
): Promise<SpotifyProOAuthStatusResponse> => {
  const response = await request<unknown>({
    method: 'GET',
    url: apiUrl('/spotify/pro/oauth/status'),
    params: { state }
  });
  return normalizeSpotifyProOAuthStatusResponse(response, state);
};

export const refreshSpotifyProSession = async (): Promise<SpotifyStatusResponse> =>
  request<SpotifyStatusResponse>({ method: 'POST', url: apiUrl('/spotify/pro/oauth/session') });

const getFirstImageUrl = (images?: SpotifyImage[] | null): string | null => {
  if (!Array.isArray(images)) {
    return null;
  }
  for (const image of images) {
    if (image && typeof image.url === 'string' && image.url.trim().length > 0) {
      return image.url;
    }
  }
  return null;
};

const toStringArray = (input: unknown): string[] => {
  if (!Array.isArray(input)) {
    return [];
  }
  return input
    .map((value) => (typeof value === 'string' ? value : null))
    .filter((value): value is string => Boolean(value && value.trim().length > 0));
};

const normalizeTrackSearchItem = (item: SpotifyRawTrack | null | undefined): SpotifyTrackSearchResult | null => {
  if (!item || typeof item !== 'object') {
    return null;
  }
  const name = typeof item.name === 'string' ? item.name.trim() : '';
  if (!name) {
    return null;
  }
  const id = typeof item.id === 'string' && item.id.trim().length > 0 ? item.id : null;
  const rawArtists = Array.isArray(item.artists) ? item.artists : [];
  const artists = rawArtists
    .map((artist) => (artist && typeof artist.name === 'string' ? artist.name.trim() : null))
    .filter((artist): artist is string => Boolean(artist));
  const albumName = item.album && typeof item.album.name === 'string' ? item.album.name.trim() : null;
  const durationMs = typeof item.duration_ms === 'number' && Number.isFinite(item.duration_ms)
    ? item.duration_ms
    : null;

  return {
    type: 'track',
    id,
    name,
    artists,
    album: albumName && albumName.length > 0 ? albumName : null,
    durationMs
  };
};

const normalizeArtistSearchItem = (
  item: SpotifyRawArtist | null | undefined
): SpotifyArtistSearchResult | null => {
  if (!item || typeof item !== 'object') {
    return null;
  }
  const name = typeof item.name === 'string' ? item.name.trim() : '';
  if (!name) {
    return null;
  }
  const id = typeof item.id === 'string' && item.id.trim().length > 0 ? item.id : null;
  const followersPayload = item.followers;
  const followers =
    followersPayload && typeof followersPayload.total === 'number' && Number.isFinite(followersPayload.total)
      ? followersPayload.total
      : null;
  return {
    type: 'artist',
    id,
    name,
    imageUrl: getFirstImageUrl(item.images ?? null),
    followers,
    genres: toStringArray(item.genres)
  };
};

const normalizeAlbumSearchItem = (item: SpotifyRawAlbum | null | undefined): SpotifyAlbumSearchResult | null => {
  if (!item || typeof item !== 'object') {
    return null;
  }
  const name = typeof item.name === 'string' ? item.name.trim() : '';
  if (!name) {
    return null;
  }
  const id = typeof item.id === 'string' && item.id.trim().length > 0 ? item.id : null;
  const artistsPayload = Array.isArray(item.artists) ? item.artists : [];
  const artists = artistsPayload
    .map((artist) => (artist && typeof artist.name === 'string' ? artist.name.trim() : null))
    .filter((artist): artist is string => Boolean(artist));
  const releaseDate = typeof item.release_date === 'string' && item.release_date.trim().length > 0
    ? item.release_date
    : null;
  return {
    type: 'album',
    id,
    name,
    imageUrl: getFirstImageUrl(item.images ?? null),
    releaseDate,
    artists
  };
};

const fetchSearchItems = async <T>(endpoint: string, query: string): Promise<T[]> => {
  const response = await request<SpotifySearchResponse<T>>({
    method: 'GET',
    url: apiUrl(endpoint),
    params: { query }
  });
  return Array.isArray(response.items) ? response.items : [];
};

export const searchSpotifyTracks = async (query: string): Promise<SpotifyTrackSearchResult[]> => {
  const rawItems = await fetchSearchItems<SpotifyRawTrack>('/spotify/search/tracks', query);
  return rawItems.map(normalizeTrackSearchItem).filter(notEmpty);
};

export const searchSpotifyArtists = async (query: string): Promise<SpotifyArtistSearchResult[]> => {
  const rawItems = await fetchSearchItems<SpotifyRawArtist>('/spotify/search/artists', query);
  return rawItems.map(normalizeArtistSearchItem).filter(notEmpty);
};

export const searchSpotifyAlbums = async (query: string): Promise<SpotifyAlbumSearchResult[]> => {
  const rawItems = await fetchSearchItems<SpotifyRawAlbum>('/spotify/search/albums', query);
  return rawItems.map(normalizeAlbumSearchItem).filter(notEmpty);
};

export const searchSpotify = async (query: string): Promise<SpotifySearchResults> => {
  const [tracks, artists, albums] = await Promise.all([
    searchSpotifyTracks(query),
    searchSpotifyArtists(query),
    searchSpotifyAlbums(query)
  ]);
  return { tracks, artists, albums };
};

export const getFollowedArtists = async (): Promise<SpotifyArtist[]> =>
  request<FollowedArtistsResponse>({ method: 'GET', url: apiUrl('/spotify/artists/followed') }).then(
    (response) => response.artists ?? []
  );

export const getArtistReleases = async (artistId: string): Promise<SpotifyArtistRelease[]> =>
  request<ArtistReleasesResponse>({ method: 'GET', url: apiUrl(`/spotify/artist/${artistId}/releases`) }).then(
    (response) => response.releases ?? []
  );

export const getSpotifyStatus = async (): Promise<SpotifyStatusResponse> =>
  request<SpotifyStatusResponse>({ method: 'GET', url: apiUrl('/spotify/status') });

export const getArtistPreferences = async (): Promise<ArtistPreferenceEntry[]> =>
  request<ArtistPreferencesResponse>({ method: 'GET', url: apiUrl('/settings/artist-preferences') }).then(
    (response) => response.preferences ?? []
  );

export const saveArtistPreferences = async (preferences: ArtistPreferenceEntry[]) =>
  request<ArtistPreferencesResponse>({
    method: 'POST',
    url: apiUrl('/settings/artist-preferences'),
    data: { preferences }
  }).then((response) => response.preferences ?? []);

export const parseSpotifyFreeInput = async (
  payload: SpotifyFreeParsePayload
): Promise<SpotifyFreeParseResponse> =>
  request<SpotifyFreeParseResponse>({ method: 'POST', url: apiUrl('/spotify/free/parse'), data: payload });

export const enqueueSpotifyFreeTracks = async (
  payload: SpotifyFreeEnqueuePayload
): Promise<SpotifyFreeEnqueueResponse> =>
  request<SpotifyFreeEnqueueResponse>({ method: 'POST', url: apiUrl('/spotify/free/enqueue'), data: payload });

export type {
  ArtistPreferenceEntry,
  NormalizedTrack,
  SpotifyAlbumSearchResult,
  SpotifyArtist,
  SpotifyArtistSearchResult,
  SpotifyArtistRelease,
  SpotifyFreeEnqueuePayload,
  SpotifyFreeEnqueueResponse,
  SpotifyFreeParsePayload,
  SpotifyFreeParseResponse,
  SpotifyProOAuthProfile,
  SpotifyProOAuthStartResponse,
  SpotifyProOAuthStatus,
  SpotifyProOAuthStatusResponse,
  SpotifySearchResults,
  SpotifyStatusResponse,
  SpotifyTrackSearchResult
};

export type { SpotifyProOAuthStartOptions };
