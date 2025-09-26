import axios, { AxiosError, AxiosRequestConfig } from 'axios';

import { API_BASE_URL } from './runtime-config';

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000
});

export interface ApiErrorContext {
  error: ApiError;
}

type ApiErrorSubscriber = (context: ApiErrorContext) => void;

const apiErrorSubscribers = new Set<ApiErrorSubscriber>();

export class ApiError extends Error {
  readonly status?: number;
  readonly data?: unknown;
  readonly originalError: unknown;
  readonly url?: string;
  readonly method?: string;
  handled = false;

  constructor({
    message,
    status,
    data,
    originalError,
    url,
    method
  }: {
    message: string;
    status?: number;
    data?: unknown;
    originalError: unknown;
    url?: string;
    method?: string;
  }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
    this.originalError = originalError;
    this.url = url;
    this.method = method;
  }

  markHandled() {
    this.handled = true;
  }
}

const extractErrorMessage = (error: AxiosError) => {
  const responseData = error.response?.data;
  if (typeof responseData === 'string' && responseData.trim().length > 0) {
    return responseData;
  }
  if (responseData && typeof responseData === 'object') {
    const record = responseData as Record<string, unknown>;
    const knownKeys = ['message', 'detail', 'error'];
    for (const key of knownKeys) {
      const value = record[key];
      if (typeof value === 'string' && value.trim().length > 0) {
        return value;
      }
    }
    if (Array.isArray(record.errors) && record.errors.length > 0) {
      const first = record.errors[0];
      if (typeof first === 'string') {
        return first;
      }
      if (first && typeof first === 'object' && typeof (first as { message?: unknown }).message === 'string') {
        return String((first as { message: unknown }).message);
      }
    }
  }
  if (typeof error.message === 'string' && error.message.trim().length > 0) {
    return error.message;
  }
  return 'Unbekannter Fehler';
};

const toApiError = (error: unknown, config?: AxiosRequestConfig): ApiError => {
  if (error instanceof ApiError) {
    return error;
  }

  if (axios.isAxiosError(error)) {
    const message = extractErrorMessage(error);
    return new ApiError({
      message,
      status: error.response?.status,
      data: error.response?.data,
      originalError: error,
      url: config?.url ?? error.config?.url,
      method: (config?.method ?? error.config?.method)?.toUpperCase()
    });
  }

  if (error instanceof Error) {
    return new ApiError({
      message: error.message,
      originalError: error,
      url: config?.url,
      method: config?.method?.toUpperCase()
    });
  }

  return new ApiError({
    message: 'Unbekannter Fehler',
    originalError: error,
    url: config?.url,
    method: config?.method?.toUpperCase()
  });
};

const notifyApiError = (apiError: ApiError) => {
  apiErrorSubscribers.forEach((subscriber) => {
    subscriber({ error: apiError });
  });
};

const redirectToSettings = () => {
  if (typeof window === 'undefined') {
    return;
  }
  if (window.location.pathname === '/settings') {
    return;
  }
  window.location.href = '/settings';
};

const request = async <T>(config: AxiosRequestConfig): Promise<T> => {
  try {
    const response = await api.request<T>(config);
    return response.data;
  } catch (error) {
    const apiError = toApiError(error, config);
    notifyApiError(apiError);
    if (apiError.status === 401 || apiError.status === 403) {
      redirectToSettings();
    }
    throw apiError;
  }
};

export const subscribeToApiErrors = (subscriber: ApiErrorSubscriber) => {
  apiErrorSubscribers.add(subscriber);
  return () => {
    apiErrorSubscribers.delete(subscriber);
  };
};

export type ConnectionStatus = 'ok' | 'fail' | 'unknown' | (string & {});

export interface WorkerHealth {
  last_seen?: string | null;
  queue_size?: number | Record<string, number | string> | string | null;
  status?: WorkerStatus;
}

export type WorkerStatus =
  | 'running'
  | 'stopped'
  | 'stale'
  | 'starting'
  | 'blocked'
  | 'errored'
  | (string & {});

export interface SystemStatusResponse {
  status?: string;
  connections?: Record<string, ConnectionStatus>;
  workers?: Record<string, WorkerHealth>;
}

export const getSystemStatus = async (): Promise<SystemStatusResponse> =>
  request<SystemStatusResponse>({
    method: 'GET',
    url: '/status'
  });

export interface SettingsResponse {
  settings: Record<string, string | null>;
  updated_at?: string;
}

export const getSettings = async (): Promise<SettingsResponse> =>
  request<SettingsResponse>({
    method: 'GET',
    url: '/settings'
  });

export interface UpdateSettingPayload {
  key: string;
  value: string | null;
}

export const updateSetting = async (payload: UpdateSettingPayload) =>
  request<void>({
    method: 'POST',
    url: '/settings',
    data: payload
  });

export const updateSettings = async (payload: UpdateSettingPayload[]) => {
  for (const entry of payload) {
    // eslint-disable-next-line no-await-in-loop
    await updateSetting(entry);
  }
};

export interface ServiceHealthResponse {
  service: string;
  status: 'ok' | 'fail';
  missing: string[];
  optional_missing: string[];
}

export type ServiceIdentifier = 'spotify' | 'plex' | 'soulseek';

export const testServiceConnection = async (service: ServiceIdentifier) =>
  request<ServiceHealthResponse>({
    method: 'GET',
    url: `/api/health/${service}`
  });

export interface ArtistPreferenceEntry {
  artist_id: string;
  release_id: string;
  selected: boolean;
}

export interface ArtistPreferencesResponse {
  preferences: ArtistPreferenceEntry[];
}

export const getArtistPreferences = async (): Promise<ArtistPreferenceEntry[]> =>
  request<ArtistPreferencesResponse>({
    method: 'GET',
    url: '/settings/artist-preferences'
  }).then((response) => response.preferences ?? []);

export const saveArtistPreferences = async (preferences: ArtistPreferenceEntry[]) =>
  request<ArtistPreferencesResponse>({
    method: 'POST',
    url: '/settings/artist-preferences',
    data: { preferences }
  }).then((response) => response.preferences ?? []);

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

export const getFollowedArtists = async (): Promise<SpotifyArtist[]> =>
  request<FollowedArtistsResponse>({
    method: 'GET',
    url: '/spotify/artists/followed'
  }).then((response) => response.artists ?? []);

export interface SpotifyArtistRelease {
  id: string;
  name: string;
  album_type?: string;
  release_type?: string;
  release_date?: string;
  total_tracks?: number;
}

export interface ArtistReleasesResponse {
  artist_id: string;
  releases: SpotifyArtistRelease[];
}

export const getArtistReleases = async (artistId: string): Promise<SpotifyArtistRelease[]> =>
  request<ArtistReleasesResponse>({
    method: 'GET',
    url: `/spotify/artist/${artistId}/releases`
  }).then((response) => response.releases ?? []);

export type SpotifyMode = 'FREE' | 'PRO';

export interface SpotifyModeResponse {
  mode: SpotifyMode;
}

export const getSpotifyMode = async (): Promise<SpotifyModeResponse> =>
  request<SpotifyModeResponse>({
    method: 'GET',
    url: '/spotify/mode'
  });

export const setSpotifyMode = async (mode: SpotifyMode): Promise<{ ok: boolean }> =>
  request<{ ok: boolean }>({
    method: 'POST',
    url: '/spotify/mode',
    data: { mode }
  });

export interface NormalizedTrack {
  source: 'user';
  kind: 'track';
  artist: string;
  title: string;
  album?: string | null;
  release_year?: number | null;
  spotify_track_id?: string | null;
  spotify_album_id?: string | null;
  query: string;
}

export interface SpotifyFreeParsePayload {
  lines: string[];
  file_token?: string | null;
}

export interface SpotifyFreeParseResponse {
  items: NormalizedTrack[];
}

export const parseSpotifyFreeInput = async (
  payload: SpotifyFreeParsePayload
): Promise<SpotifyFreeParseResponse> =>
  request<SpotifyFreeParseResponse>({
    method: 'POST',
    url: '/spotify/free/parse',
    data: payload
  });

export interface SpotifyFreeEnqueuePayload {
  items: NormalizedTrack[];
}

export interface SpotifyFreeEnqueueResponse {
  queued: number;
  skipped: number;
}

export const enqueueSpotifyFreeTracks = async (
  payload: SpotifyFreeEnqueuePayload
): Promise<SpotifyFreeEnqueueResponse> =>
  request<SpotifyFreeEnqueueResponse>({
    method: 'POST',
    url: '/spotify/free/enqueue',
    data: payload
  });

export interface SpotifyFreeUploadPayload {
  filename: string;
  content: string;
}

export interface SpotifyFreeUploadResponse {
  file_token: string;
}

export const uploadSpotifyFreeFile = async (
  payload: SpotifyFreeUploadPayload
): Promise<SpotifyFreeUploadResponse> =>
  request<SpotifyFreeUploadResponse>({
    method: 'POST',
    url: '/spotify/free/upload',
    data: payload
  });

export interface DownloadEntry {
  id: number | string;
  filename: string;
  status: string;
  progress: number;
  created_at?: string;
  updated_at?: string;
  priority: number;
  username?: string | null;
}

export interface FetchDownloadsOptions {
  includeAll?: boolean;
  limit?: number;
  offset?: number;
  status?: string;
}

const extractDownloadArray = (value: unknown): DownloadEntry[] => {
  if (Array.isArray(value)) {
    return value as DownloadEntry[];
  }
  if (value && typeof value === 'object' && Array.isArray((value as { downloads?: unknown[] }).downloads)) {
    return (value as { downloads: DownloadEntry[] }).downloads;
  }
  return [];
};

const normalizeDownloadEntry = (entry: DownloadEntry | (DownloadEntry & { state?: string })): DownloadEntry => {
  const status = (entry.status ?? (entry as { state?: string }).state ?? 'unknown').toString();
  const priorityValue = (entry as { priority?: unknown }).priority;
  const priority =
    typeof priorityValue === 'number'
      ? priorityValue
      : typeof priorityValue === 'string'
        ? Number.parseInt(priorityValue, 10) || 0
        : 0;

  return {
    id: entry.id,
    filename: entry.filename ?? '',
    status,
    progress: entry.progress ?? 0,
    created_at: entry.created_at,
    updated_at: entry.updated_at,
    priority,
    username: entry.username ?? null
  };
};

export const getDownloads = async (options: FetchDownloadsOptions = {}): Promise<DownloadEntry[]> => {
  const params: Record<string, string | number | boolean> = {};
  if (options.includeAll) {
    params.all = true;
  }
  if (typeof options.limit === 'number') {
    params.limit = options.limit;
  }
  if (typeof options.offset === 'number') {
    params.offset = options.offset;
  }
  if (options.status) {
    params.status = options.status;
  }

  const payload = await request<unknown>({
    method: 'GET',
    url: '/api/downloads',
    params: Object.keys(params).length > 0 ? params : undefined
  });
  return extractDownloadArray(payload).map(normalizeDownloadEntry);
};

export const cancelDownload = async (id: string | number) =>
  request<void>({
    method: 'DELETE',
    url: `/api/download/${id}`
  });

export const retryDownload = async (id: string | number): Promise<DownloadEntry> =>
  request<unknown>({
    method: 'POST',
    url: `/api/download/${id}/retry`
  }).then((payload) => {
    const downloads = extractDownloadArray(payload).map(normalizeDownloadEntry);
    return (
      downloads[0] ??
      normalizeDownloadEntry({
        id,
        filename: '',
        status: 'queued',
        progress: 0,
        priority: 0
      })
    );
  });

export const updateDownloadPriority = async (id: string | number, priority: number) =>
  request<DownloadEntry>({
    method: 'PATCH',
    url: `/api/download/${id}/priority`,
    data: { priority }
  }).then(normalizeDownloadEntry);

export interface StartDownloadPayload {
  track_id: string;
}

export const startDownload = async (payload: StartDownloadPayload): Promise<DownloadEntry> =>
  request<unknown>({
    method: 'POST',
    url: '/api/download',
    data: payload
  }).then((response) => {
    const downloads = extractDownloadArray(response).map(normalizeDownloadEntry);
    return (
      downloads[0] ??
      normalizeDownloadEntry({
        id: '',
        filename: '',
        status: 'queued',
        progress: 0,
        priority: 0
      })
    );
  });

export interface DownloadExportFilters {
  status?: string;
  from?: string;
  to?: string;
}

export const exportDownloads = async (format: 'csv' | 'json', filters: DownloadExportFilters = {}) => {
  const params: Record<string, string> = { format };
  if (filters.status) {
    params.status = filters.status;
  }
  if (filters.from) {
    params.from = filters.from;
  }
  if (filters.to) {
    params.to = filters.to;
  }
  return request<Blob>({
    method: 'GET',
    url: '/api/downloads/export',
    params,
    responseType: 'blob'
  });
};

export type ActivityType =
  | 'sync'
  | 'autosync'
  | 'search'
  | 'download'
  | 'download_retry'
  | 'download_retry_failed'
  | 'download_retry_scheduled'
  | 'metadata'
  | 'worker'
  | 'worker_started'
  | 'worker_stopped'
  | 'worker_blocked'
  | (string & {});

export type ActivityStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'started'
  | 'stopped'
  | 'stale'
  | 'blocked'
  | (string & {});

export interface ActivityItem {
  timestamp: string;
  type: ActivityType;
  status: ActivityStatus;
  details?: Record<string, unknown>;
}

const parseActivityDetails = (value: unknown): Record<string, unknown> | undefined => {
  if (!value) {
    return undefined;
  }
  if (typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch (error) {
      console.warn('Failed to parse activity details', error);
    }
  }
  return undefined;
};

const normalizeActivityItem = (entry: unknown): ActivityItem | null => {
  if (!entry || typeof entry !== 'object') {
    return null;
  }
  const record = entry as Record<string, unknown>;
  if (typeof record.timestamp !== 'string' || typeof record.type !== 'string' || typeof record.status !== 'string') {
    return null;
  }
  const details = parseActivityDetails(record.details);
  return {
    timestamp: record.timestamp,
    type: record.type as ActivityType,
    status: record.status as ActivityStatus,
    details
  };
};

export const getActivityFeed = async (): Promise<ActivityItem[]> => {
  const payload = await request<unknown>({
    method: 'GET',
    url: '/api/activity'
  });
  if (Array.isArray(payload)) {
    return payload.map(normalizeActivityItem).filter((item): item is ActivityItem => item !== null);
  }
  if (payload && typeof payload === 'object' && Array.isArray((payload as { items?: unknown[] }).items)) {
    return (payload as { items: unknown[] }).items
      .map(normalizeActivityItem)
      .filter((item): item is ActivityItem => item !== null);
  }
  return [];
};

export const triggerManualSync = async () =>
  request<void>({
    method: 'POST',
    url: '/api/sync'
  });
