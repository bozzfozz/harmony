import axios from 'axios';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 10000
});

export interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'syncing' | 'idle';
  lastSync?: string;
  items?: number;
}

export interface JobItem {
  id: string;
  name: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress: number;
  updatedAt: string;
}

export interface SystemOverview {
  hostname: string;
  uptime: string;
  cpuLoad: number;
  memoryUsage: number;
  diskUsage: number;
  version: string;
}

export interface SpotifyOverview {
  playlists: number;
  artists: number;
  tracks: number;
  lastSync: string;
}

export interface PlexOverview {
  libraries: number;
  sessions: number;
  lastSync: string;
}

export interface SoulseekOverview {
  downloads: number;
  uploads: number;
  queue: number;
  lastSync: string;
}

export interface BeetsOverview {
  albums: number;
  artists: number;
  tracks: number;
  lastSync: string;
}

export interface MatchingStats {
  pending: number;
  processed: number;
  conflicts: number;
  lastRun: string;
}

export interface SettingsData {
  spotify: Record<string, string>;
  plex: Record<string, string>;
  soulseek: Record<string, string>;
  beets: Record<string, string>;
}

export const fetchSystemOverview = async () => {
  const response = await apiClient.get<SystemOverview>('/settings/system');
  return response.data;
};

export const fetchServices = async () => {
  const response = await apiClient.get<ServiceStatus[]>('/settings/services');
  return response.data;
};

export const fetchJobs = async () => {
  const response = await apiClient.get<JobItem[]>('/matching/jobs');
  return response.data;
};

export const fetchSpotifyOverview = async () => {
  const response = await apiClient.get<SpotifyOverview>('/spotify');
  return response.data;
};

export const fetchPlexOverview = async () => {
  const response = await apiClient.get<PlexOverview>('/plex');
  return response.data;
};

export const fetchSoulseekOverview = async () => {
  const response = await apiClient.get<SoulseekOverview>('/soulseek');
  return response.data;
};

export const fetchBeetsOverview = async () => {
  const response = await apiClient.get<BeetsOverview>('/beets');
  return response.data;
};

export const fetchMatchingStats = async () => {
  const response = await apiClient.get<MatchingStats>('/matching');
  return response.data;
};

export const fetchSettings = async () => {
  const response = await apiClient.get<SettingsData>('/settings');
  return response.data;
};

export const updateSettings = async (payload: SettingsData) => {
  const response = await apiClient.put<SettingsData>('/settings', payload);
  return response.data;
};
