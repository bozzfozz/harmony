import { apiUrl, request } from '../client';
import type {
  ArtistPreferenceEntry,
  ArtistPreferencesResponse,
  ArtistReleasesResponse,
  FollowedArtistsResponse,
  NormalizedTrack,
  SpotifyArtist,
  SpotifyArtistRelease,
  SpotifyFreeEnqueuePayload,
  SpotifyFreeEnqueueResponse,
  SpotifyFreeParsePayload,
  SpotifyFreeParseResponse,
  SpotifyFreeUploadPayload,
  SpotifyFreeUploadResponse,
  SpotifyMode,
  SpotifyModeResponse
} from '../types';

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
  SpotifyArtist,
  SpotifyArtistRelease,
  SpotifyFreeEnqueuePayload,
  SpotifyFreeEnqueueResponse,
  SpotifyFreeParsePayload,
  SpotifyFreeParseResponse,
  SpotifyFreeUploadPayload,
  SpotifyFreeUploadResponse,
  SpotifyMode,
  SpotifyModeResponse
};
