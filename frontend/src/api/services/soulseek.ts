import { apiUrl, request } from '../client';
import { getSettings } from './system';
import type {
  IntegrationsData,
  IntegrationsResponse,
  ProviderInfo,
  SettingsResponse,
  SoulseekStatusResponse,
  SoulseekUploadEntry,
  SoulseekUploadsResponse
} from '../types';

const SECRET_KEY_PATTERN = /(SECRET|TOKEN|KEY|PASSWORD)/iu;
const KNOWN_SOULSEEK_KEYS = ['SLSKD_URL', 'SLSKD_API_KEY'];

const toStringOrNull = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value);
  }
  return null;
};

const toNumberOrNull = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const ensureArray = (value: unknown): unknown[] => {
  if (Array.isArray(value)) {
    return value;
  }
  if (value === null || value === undefined) {
    return [];
  }
  return [value];
};

const normalizeUpload = (entry: unknown): NormalizedSoulseekUpload | null => {
  if (!entry || typeof entry !== 'object') {
    return null;
  }

  const record = entry as SoulseekUploadEntry;
  const id = toStringOrNull(record.id);
  const filename = toStringOrNull(record.filename);
  const username = toStringOrNull(record.username ?? (record as { user?: unknown }).user);
  const state = toStringOrNull(record.state) ?? 'unknown';
  const progress = toNumberOrNull(record.progress);
  const size = toNumberOrNull(record.size ?? (record as { filesize?: unknown }).filesize);
  const speed = toNumberOrNull(record.speed ?? (record as { speed_bps?: unknown }).speed_bps);
  const queuedAt = toStringOrNull(record.queued_at ?? (record as { queuedAt?: unknown }).queuedAt);
  const startedAt = toStringOrNull(record.started_at ?? (record as { startedAt?: unknown }).startedAt);
  const completedAt = toStringOrNull(
    record.completed_at ?? (record as { completedAt?: unknown }).completedAt
  );

  return {
    id,
    filename,
    username,
    state,
    progress,
    size,
    speed,
    queuedAt,
    startedAt,
    completedAt,
    raw: record
  };
};

const normalizeProvider = (entry: unknown): ProviderInfo | null => {
  if (!entry || typeof entry !== 'object') {
    return null;
  }
  const record = entry as Record<string, unknown>;
  const name = toStringOrNull(record.name);
  if (!name) {
    return null;
  }
  const status = toStringOrNull(record.status) ?? 'unknown';
  const details =
    record.details && typeof record.details === 'object' && !Array.isArray(record.details)
      ? (record.details as Record<string, unknown>)
      : null;
  return { name, status, details };
};

const prettifySettingKey = (key: string): string => {
  const labelMap: Record<string, string> = {
    SLSKD_URL: 'Basis-URL',
    SLSKD_API_KEY: 'API-Schlüssel'
  };
  if (labelMap[key]) {
    return labelMap[key];
  }
  const normalized = key.replace(/^SLSKD_/u, '').replace(/_/gu, ' ');
  return normalized
    .split(' ')
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1).toLowerCase())
    .join(' ');
};

export interface NormalizedSoulseekUpload {
  id: string | null;
  filename: string | null;
  username: string | null;
  state: string;
  progress: number | null;
  size: number | null;
  speed: number | null;
  queuedAt: string | null;
  startedAt: string | null;
  completedAt: string | null;
  raw: SoulseekUploadEntry;
}

export interface SoulseekConfigurationEntry {
  key: string;
  label: string;
  value: string | null;
  displayValue: string | null;
  present: boolean;
  masked: boolean;
}

export const getSoulseekStatus = async (): Promise<SoulseekStatusResponse> =>
  request<SoulseekStatusResponse>({ method: 'GET', url: apiUrl('/soulseek/status') });

export const getSoulseekUploads = async ({
  includeAll = false
}: { includeAll?: boolean } = {}): Promise<NormalizedSoulseekUpload[]> => {
  const endpoint = includeAll ? '/soulseek/uploads/all' : '/soulseek/uploads';
  const payload = await request<SoulseekUploadsResponse>({ method: 'GET', url: apiUrl(endpoint) });
  const uploads = ensureArray(payload.uploads);
  return uploads.map(normalizeUpload).filter((entry): entry is NormalizedSoulseekUpload => entry !== null);
};

export const getIntegrationsReport = async (): Promise<IntegrationsData> => {
  const payload = await request<IntegrationsResponse>({ method: 'GET', url: apiUrl('/integrations') });
  if (!payload.ok || !payload.data) {
    throw new Error('Integrations response missing data');
  }
  const providers = ensureArray(payload.data.providers)
    .map(normalizeProvider)
    .filter((provider): provider is ProviderInfo => provider !== null);
  return {
    overall: toStringOrNull(payload.data.overall) ?? 'unknown',
    providers
  };
};

export const getSoulseekConfiguration = async (): Promise<SoulseekConfigurationEntry[]> => {
  const settingsPayload = await getSettings();
  const entries = normalizeSoulseekSettings(settingsPayload);
  return entries.sort((a, b) => a.label.localeCompare(b.label, 'de'));
};

const normalizeSoulseekSettings = (payload: SettingsResponse): SoulseekConfigurationEntry[] => {
  const settings = payload.settings ?? {};
  const keys = new Set<string>(KNOWN_SOULSEEK_KEYS);
  Object.keys(settings)
    .filter((key) => key.startsWith('SLSKD_'))
    .forEach((key) => keys.add(key));

  return Array.from(keys).map((key) => {
    const rawValue = settings[key];
    const normalizedValue = toStringOrNull(rawValue);
    const present = normalizedValue !== null;
    const masked = present && SECRET_KEY_PATTERN.test(key);
    return {
      key,
      label: prettifySettingKey(key),
      value: normalizedValue,
      displayValue: masked ? '••••••' : normalizedValue,
      present,
      masked
    };
  });
};

export type { IntegrationsData };
