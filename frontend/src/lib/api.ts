import axios from 'axios';

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 10000
});

export interface SettingsResponse {
  settings: Record<string, string | null>;
  updated_at: string;
}

export interface UpdateSettingPayload {
  key: string;
  value: string | null;
}

export interface StatusResponse {
  status: string;
  artist_count?: number;
  album_count?: number;
  track_count?: number;
  last_scan?: string;
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

export interface SpotifyImage {
  url?: string;
  width?: number;
  height?: number;
}

export interface SpotifyArtist {
  id: string;
  name: string;
  images?: SpotifyImage[];
  followers?: { total?: number };
}

export interface FollowedArtistsResponse {
  artists: SpotifyArtist[];
}

export interface SpotifyArtistSummary {
  name?: string;
}

export interface SpotifyAlbumSummary {
  name?: string;
}

export interface SpotifyArtistRelease {
  id: string;
  name: string;
  album_type?: string;
  release_date?: string;
  total_tracks?: number;
}

export interface ArtistReleasesResponse {
  artist_id: string;
  releases: SpotifyArtistRelease[];
}

export interface SpotifyTrackSummary {
  id?: string;
  name?: string;
  artists?: SpotifyArtistSummary[];
  album?: SpotifyAlbumSummary;
  duration_ms?: number;
}

export interface SpotifySearchResponse {
  items: SpotifyTrackSummary[];
}

export interface PlexStatusResponse {
  status: string;
  sessions?: unknown[];
  library?: Record<string, unknown>;
}

export type PlexLibrariesResponse = Record<string, unknown>;

export interface SoulseekDownloadEntry {
  id: number;
  filename: string;
  state: string;
  progress: number;
  created_at: string;
  updated_at: string;
}

export interface SoulseekDownloadsResponse {
  downloads: SoulseekDownloadEntry[];
}

export interface MatchingRequestPayload {
  spotify_track: Record<string, unknown>;
  candidates: Record<string, unknown>[];
}

export interface AlbumMatchingRequestPayload {
  spotify_album: Record<string, unknown>;
  candidates: Record<string, unknown>[];
}

export interface MatchingResponsePayload {
  best_match: Record<string, unknown> | null;
  confidence: number;
}

export interface BeetsImportRequest {
  path: string;
  quiet?: boolean;
  autotag?: boolean;
}

export interface BeetsImportResponse {
  success: boolean;
  message: string;
}

export interface BeetsStatsResponse {
  stats: Record<string, string>;
}

export interface DownloadEntry {
  id: number | string;
  filename: string;
  status: string;
  progress: number;
  created_at?: string;
}

export interface StartDownloadPayload {
  track_id: string;
}

export interface ArtistPreferenceEntry {
  artist_id: string;
  release_id: string;
  selected: boolean;
}

export interface ArtistPreferencesResponse {
  preferences: ArtistPreferenceEntry[];
}

export type ActivityType = 'sync' | 'search' | 'download' | 'metadata' | (string & {});

export type ActivityStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | (string & {});

export interface ActivityItem {
  timestamp: string;
  type: ActivityType;
  status: ActivityStatus;
  details?: Record<string, unknown>;
}

export const fetchSettings = async (): Promise<SettingsResponse> => {
  const { data } = await api.get<SettingsResponse>('/settings');
  return data;
};

export const updateSetting = async (setting: UpdateSettingPayload): Promise<void> => {
  await api.post('/settings', setting);
};

export const updateSettings = async (settings: UpdateSettingPayload[]): Promise<void> => {
  for (const setting of settings) {
    await updateSetting(setting);
  }
};

export const fetchSpotifyStatus = async (): Promise<StatusResponse> => {
  const { data } = await api.get<StatusResponse>('/spotify/status');
  return data;
};

export const fetchSpotifyPlaylists = async (): Promise<SpotifyPlaylist[]> => {
  const { data } = await api.get<SpotifyPlaylistsResponse>('/spotify/playlists');
  return data.playlists;
};

export const fetchFollowedArtists = async (): Promise<SpotifyArtist[]> => {
  const { data } = await api.get<FollowedArtistsResponse>('/spotify/artists/followed');
  return data.artists;
};

export const fetchArtistReleases = async (
  artistId: string
): Promise<SpotifyArtistRelease[]> => {
  const { data } = await api.get<ArtistReleasesResponse>(`/spotify/artist/${artistId}/releases`);
  return data.releases;
};

export const searchSpotifyTracks = async (query: string): Promise<SpotifyTrackSummary[]> => {
  const { data } = await api.get<SpotifySearchResponse>('/spotify/search/tracks', {
    params: { query }
  });
  return data.items;
};

export const fetchPlexStatus = async (): Promise<PlexStatusResponse> => {
  const { data } = await api.get<PlexStatusResponse>('/plex/status');
  return data;
};

export const fetchPlexLibraries = async (): Promise<PlexLibrariesResponse> => {
  const { data } = await api.get<PlexLibrariesResponse>('/plex/library/sections');
  return data;
};

export const fetchSoulseekStatus = async (): Promise<StatusResponse> => {
  const { data } = await api.get<StatusResponse>('/soulseek/status');
  return data;
};

export const fetchSoulseekDownloads = async (): Promise<SoulseekDownloadEntry[]> => {
  const { data } = await api.get<SoulseekDownloadsResponse>('/soulseek/downloads');
  return data.downloads;
};

export const fetchArtistPreferences = async (): Promise<ArtistPreferenceEntry[]> => {
  const { data } = await api.get<ArtistPreferencesResponse>('/settings/artist-preferences');
  return data.preferences;
};

export const runSpotifyToPlexMatch = async (
  payload: MatchingRequestPayload
): Promise<MatchingResponsePayload> => {
  const { data } = await api.post<MatchingResponsePayload>('/matching/spotify-to-plex', payload);
  return data;
};

export const runSpotifyToSoulseekMatch = async (
  payload: MatchingRequestPayload
): Promise<MatchingResponsePayload> => {
  const { data } = await api.post<MatchingResponsePayload>('/matching/spotify-to-soulseek', payload);
  return data;
};

export const saveArtistPreferences = async (
  preferences: ArtistPreferenceEntry[]
): Promise<ArtistPreferenceEntry[]> => {
  const { data } = await api.post<ArtistPreferencesResponse>('/settings/artist-preferences', {
    preferences
  });
  return data.preferences;
};

export const runSpotifyToPlexAlbumMatch = async (
  payload: AlbumMatchingRequestPayload
): Promise<MatchingResponsePayload> => {
  const { data } = await api.post<MatchingResponsePayload>(
    '/matching/spotify-to-plex-album',
    payload
  );
  return data;
};

export const runBeetsImport = async (payload: BeetsImportRequest): Promise<BeetsImportResponse> => {
  const { data } = await api.post<BeetsImportResponse>('/beets/import', payload);
  return data;
};

export const fetchBeetsStats = async (): Promise<BeetsStatsResponse> => {
  const { data } = await api.get<BeetsStatsResponse>('/beets/stats');
  return data;
};

export const fetchActiveDownloads = async (): Promise<DownloadEntry[]> => {
  const { data } = await api.get('/api/download');
  if (Array.isArray(data)) {
    return data as DownloadEntry[];
  }
  if (Array.isArray((data as { downloads?: DownloadEntry[] }).downloads)) {
    return (data as { downloads: DownloadEntry[] }).downloads;
  }
  return [];
};

export const startDownload = async (payload: StartDownloadPayload): Promise<DownloadEntry> => {
  const { data } = await api.post('/api/download', payload);
  if (Array.isArray((data as { downloads?: DownloadEntry[] }).downloads)) {
    const [first] = (data as { downloads: DownloadEntry[] }).downloads;
    return first;
  }
  return data as DownloadEntry;
};

export const fetchActivityFeed = async (): Promise<ActivityItem[]> => {
  const { data } = await api.get('/api/activity');
  if (Array.isArray(data)) {
    return data as ActivityItem[];
  }
  if (Array.isArray((data as { items?: ActivityItem[] }).items)) {
    return (data as { items: ActivityItem[] }).items;
  }
  return [];
};
