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
  SpotifyFreeUploadPayload,
  SpotifyFreeUploadResponse,
  SpotifyImage,
  SpotifyMode,
  SpotifyModeResponse,
  SpotifyRawAlbum,
  SpotifyRawArtist,
  SpotifyRawTrack,
  SpotifySearchResponse,
  SpotifySearchResults,
  SpotifyTrackSearchResult
} from '../types';

const notEmpty = <T>(value: T | null | undefined): value is T => value !== null && value !== undefined;

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

export const getSpotifyMode = async (): Promise<SpotifyModeResponse> =>
  request<SpotifyModeResponse>({ method: 'GET', url: apiUrl('/spotify/mode') });

export const setSpotifyMode = async (mode: SpotifyMode): Promise<{ ok: boolean }> =>
  request<{ ok: boolean }>({ method: 'POST', url: apiUrl('/spotify/mode'), data: { mode } });

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

export const uploadSpotifyFreeFile = async (
  payload: SpotifyFreeUploadPayload
): Promise<SpotifyFreeUploadResponse> =>
  request<SpotifyFreeUploadResponse>({ method: 'POST', url: apiUrl('/spotify/free/upload'), data: payload });

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
  SpotifyFreeUploadPayload,
  SpotifyFreeUploadResponse,
  SpotifySearchResults,
  SpotifyMode,
  SpotifyModeResponse,
  SpotifyTrackSearchResult
};
