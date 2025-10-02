import { apiUrl, request } from '../client';
import type {
  ActivityItem,
  ActivityStatus,
  ActivityType,
  SecretValidationResponse,
  SecretProvider,
  ServiceHealthResponse,
  SettingsResponse,
  SystemStatusResponse,
  UpdateSettingPayload
} from '../types';

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

export const getSystemStatus = async (): Promise<SystemStatusResponse> =>
  request<SystemStatusResponse>({ method: 'GET', url: apiUrl('/status') });

export const triggerManualSync = async () =>
  request<void>({ method: 'POST', url: apiUrl('/sync'), responseType: 'void' });

export const getSettings = async (): Promise<SettingsResponse> =>
  request<SettingsResponse>({ method: 'GET', url: apiUrl('/settings') });

export const updateSetting = async (payload: UpdateSettingPayload) =>
  request<void>({ method: 'POST', url: apiUrl('/settings'), data: payload, responseType: 'void' });

export const updateSettings = async (payload: UpdateSettingPayload[]) => {
  for (const entry of payload) {
    // eslint-disable-next-line no-await-in-loop
    await updateSetting(entry);
  }
};

export const testServiceConnection = async (service: string) =>
  request<ServiceHealthResponse>({ method: 'GET', url: apiUrl(`/health/${service}`) });

export const validateSecret = async (provider: SecretProvider, override?: string) => {
  const data = typeof override === 'string' ? { value: override } : undefined;
  return request<SecretValidationResponse>({ method: 'POST', url: apiUrl(`/secrets/${provider}/validate`), data });
};

export const getActivityFeed = async (): Promise<ActivityItem[]> => {
  const payload = await request<unknown>({ method: 'GET', url: apiUrl('/activity') });
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

export type { ActivityItem, ActivityStatus, ActivityType, SecretProvider, ServiceHealthResponse, SettingsResponse };
