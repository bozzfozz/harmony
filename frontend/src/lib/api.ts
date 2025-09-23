import axios from 'axios';

const resolveBaseUrl = () => {
  if (typeof window !== 'undefined') {
    return (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? '';
  }
  return process.env.VITE_API_BASE_URL ?? 'http://localhost';
};

export const apiClient = axios.create({
  baseURL: resolveBaseUrl(),
  timeout: 15000
});

export interface RootStatusResponse {
  status: string;
  version: string;
}

export interface StatusResponse {
  status: string;
}

export interface SpotifyPlaylist {
  id: string;
  name: string;
  track_count: number;
  updated_at: string;
}

export interface SpotifyPlaylistsResponse {
  playlists: SpotifyPlaylist[];
}

export interface SpotifySearchResponse {
  items: Array<Record<string, unknown>>;
}

export interface PlexStatusResponse {
  status: string;
  sessions?: Record<string, unknown>;
  library?: Record<string, number>;
}

export interface SoulseekDownloadEntry {
  id: number;
  filename: string;
  state: string;
  progress: number;
  created_at: string;
  updated_at: string;
}

export interface SoulseekDownloadStatusResponse {
  downloads: SoulseekDownloadEntry[];
}

export interface SoulseekSearchResponse {
  results: Array<Record<string, unknown>>;
  raw?: Record<string, unknown> | null;
}

export interface SettingsResponse {
  settings: Record<string, string | null>;
  updated_at: string;
}

export interface UpdateSettingPayload {
  key: string;
  value: string | null;
}

const unwrap = async <T>(promise: Promise<{ data: T }>) => {
  const response = await promise;
  return response.data;
};

export const fetchRootStatus = () => unwrap(apiClient.get<RootStatusResponse>('/'));
export const fetchSettings = () => unwrap(apiClient.get<SettingsResponse>('/settings'));
export const updateSetting = (payload: UpdateSettingPayload) =>
  unwrap(apiClient.post<SettingsResponse>('/settings', payload));
export const fetchSpotifyStatus = () => unwrap(apiClient.get<StatusResponse>('/spotify/status'));
export const fetchSpotifyPlaylists = () => unwrap(apiClient.get<SpotifyPlaylistsResponse>('/spotify/playlists'));
export const searchSpotifyTracks = (query: string) =>
  unwrap(apiClient.get<SpotifySearchResponse>('/spotify/search/tracks', { params: { query } }));
export const fetchPlexStatus = () => unwrap(apiClient.get<PlexStatusResponse>('/plex/status'));
export const fetchSoulseekStatus = () => unwrap(apiClient.get<StatusResponse>('/soulseek/status'));
export const fetchSoulseekDownloads = () => unwrap(apiClient.get<SoulseekDownloadStatusResponse>('/soulseek/downloads'));
export const searchSoulseek = (query: string) => unwrap(apiClient.post<SoulseekSearchResponse>('/soulseek/search', { query }));
