export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export type ConnectionStatus = 'ok' | 'fail' | 'unknown' | (string & {});

export type SecretProvider = 'slskd_api_key' | 'spotify_client_secret';

export interface ApiEnvelopeError {
  code: string;
  message: string;
  meta?: Record<string, unknown>;
}

export interface ApiEnvelope<T> {
  ok: boolean;
  data: T | null;
  error: ApiEnvelopeError | null;
}

export type ValidationMode = 'live' | 'format';

export interface SecretValidatedPayload {
  mode: ValidationMode;
  valid: boolean;
  reason?: string;
  note?: string;
  at: string;
}

export interface SecretValidationData {
  provider: SecretProvider;
  validated: SecretValidatedPayload;
}

export type SecretValidationResponse = ApiEnvelope<SecretValidationData>;

export type WorkerStatus =
  | 'running'
  | 'stopped'
  | 'stale'
  | 'starting'
  | 'blocked'
  | 'errored'
  | (string & {});

export interface WorkerHealth {
  last_seen?: string | null;
  queue_size?: number | Record<string, number | string> | string | null;
  status?: WorkerStatus;
}

export interface SystemStatusResponse {
  status?: string;
  connections?: Record<string, ConnectionStatus>;
  workers?: Record<string, WorkerHealth>;
}

export interface SettingsResponse {
  settings: Record<string, string | null>;
  updated_at?: string;
}

export interface UpdateSettingPayload {
  key: string;
  value: string | null;
}

export interface ServiceHealthResponse {
  service: string;
  status: 'ok' | 'fail';
  missing: string[];
  optional_missing: string[];
}

export type ServiceIdentifier = 'spotify' | 'plex' | 'soulseek';

export interface ArtistPreferenceEntry {
  artist_id: string;
  release_id: string;
  selected: boolean;
}

export interface ArtistPreferencesResponse {
  preferences: ArtistPreferenceEntry[];
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

export type SpotifyMode = 'FREE' | 'PRO';

export interface SpotifyModeResponse {
  mode: SpotifyMode;
}

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

export interface SpotifyFreeUploadPayload {
  filename: string;
  content: string;
}

export interface SpotifyFreeParseResponse {
  items: NormalizedTrack[];
}

export interface SpotifyFreeUploadResponse {
  file_token: string;
}

export interface SpotifyFreeEnqueuePayload {
  items: NormalizedTrack[];
}

export interface SpotifyFreeEnqueueResponse {
  queued: number;
  skipped: number;
}

export interface WatchlistArtistEntry {
  id: number | string;
  spotify_artist_id: string;
  name: string;
  last_checked: string | null;
  created_at: string;
}

export interface WatchlistArtistPayload {
  spotify_artist_id: string;
  name: string;
}

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
  page?: number;
  pageSize?: number;
}

export interface DownloadStats {
  failed: number;
  [key: string]: number;
}

export interface RetryAllFailedResponse {
  requeued: number;
  skipped: number;
}

export interface StartDownloadPayload {
  track_id: string;
}

export interface DownloadExportFilters {
  status?: string;
  from?: string;
  to?: string;
}
