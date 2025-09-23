import axios from 'axios';

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 10000
});

export interface SettingsResponse {
  settings: Record<string, string>;
}

export interface UpdateSettingPayload {
  key: string;
  value: string | null;
}

export interface SystemOverviewResponse {
  cpuUsage: number;
  memoryUsage: number;
  storageUsage: number;
  runningServices: number;
}

export interface ServiceSummary {
  name: string;
  status: 'running' | 'stopped' | 'paused';
  uptime: string;
}

export interface JobSummary {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'success' | 'error';
  updatedAt: string;
}

export interface SpotifyOverviewResponse {
  playlists: number;
  artists: number;
  tracks: number;
  lastSync: string;
}

export interface PlexOverviewResponse {
  libraries: number;
  users: number;
  sessions: number;
  lastSync: string;
}

export interface SoulseekOverviewResponse {
  downloads: number;
  uploads: number;
  queue: number;
  lastSync: string;
}

export interface BeetsOverviewResponse {
  albums: number;
  artists: number;
  tracks: number;
  lastSync: string;
}

export interface MatchingStatsResponse {
  pending: number;
  processed: number;
  conflicts: number;
  lastRun: string;
}

export interface MatchingHistoryEntry {
  id: string;
  source: string;
  matched: number;
  unmatched: number;
  createdAt: string;
}

export const fetchSettings = async (): Promise<SettingsResponse> => {
  const { data } = await api.get<SettingsResponse>('/settings');
  return data;
};

export const updateSettings = async (settings: UpdateSettingPayload[]): Promise<void> => {
  await api.put('/settings', { settings });
};

export const updateSetting = async (setting: UpdateSettingPayload): Promise<void> => {
  await updateSettings([setting]);
};

export const fetchSystemOverview = async (): Promise<SystemOverviewResponse> => {
  const { data } = await api.get<SystemOverviewResponse>('/system/overview');
  return data;
};

export const fetchServices = async (): Promise<ServiceSummary[]> => {
  const { data } = await api.get<ServiceSummary[]>('/system/services');
  return data;
};

export const fetchJobs = async (): Promise<JobSummary[]> => {
  const { data } = await api.get<JobSummary[]>('/system/jobs');
  return data;
};

export const fetchSpotifyOverview = async (): Promise<SpotifyOverviewResponse> => {
  const { data } = await api.get<SpotifyOverviewResponse>('/spotify/overview');
  return data;
};

export const fetchPlexOverview = async (): Promise<PlexOverviewResponse> => {
  const { data } = await api.get<PlexOverviewResponse>('/plex/overview');
  return data;
};

export const fetchSoulseekOverview = async (): Promise<SoulseekOverviewResponse> => {
  const { data } = await api.get<SoulseekOverviewResponse>('/soulseek/overview');
  return data;
};

export const fetchBeetsOverview = async (): Promise<BeetsOverviewResponse> => {
  const { data } = await api.get<BeetsOverviewResponse>('/beets/overview');
  return data;
};

export const fetchMatchingStats = async (): Promise<MatchingStatsResponse> => {
  const { data } = await api.get<MatchingStatsResponse>('/matching/stats');
  return data;
};

export const fetchMatchingHistory = async (): Promise<MatchingHistoryEntry[]> => {
  const { data } = await api.get<MatchingHistoryEntry[]>('/matching/history');
  return data;
};
