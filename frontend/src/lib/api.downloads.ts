import { useCallback, useState } from 'react';

import { ApiEnvelope, ApiError, apiUrl, request } from './api';
import { useMutation, useQuery, useQueryClient } from './query';

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

export const DOWNLOAD_STATS_QUERY_KEY = ['downloads', 'stats'] as const;

const isDevEnvironment = () =>
  ((globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.NODE_ENV ?? '') !==
  'production';

const unwrapEnvelope = <T>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'ok' in (payload as Record<string, unknown>)) {
    const envelope = payload as ApiEnvelope<T>;
    if (!envelope.ok) {
      const code = envelope.error?.code ?? 'UNKNOWN_ERROR';
      const message = envelope.error?.message ?? code;
      throw new ApiError({
        message,
        status: 400,
        data: envelope,
        originalError: new Error(code)
      });
    }
    return (envelope.data ?? ({} as T)) as T;
  }
  return payload as T;
};

const normalizePriority = (value: unknown): number => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
};

const normalizeProgress = (value: unknown): number => {
  if (typeof value === 'number') {
    const bounded = Math.max(0, Math.min(100, value));
    return Number.isFinite(bounded) ? bounded : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) {
      return Math.max(0, Math.min(100, parsed));
    }
  }
  return 0;
};

const normalizeStatus = (entry: Record<string, unknown>): string => {
  const rawStatus = entry.status ?? entry.state ?? 'unknown';
  return typeof rawStatus === 'string' ? rawStatus : String(rawStatus);
};

const normalizeDownloadEntry = (value: unknown): DownloadEntry | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (record.id === undefined) {
    return null;
  }
  return {
    id: record.id as number | string,
    filename: typeof record.filename === 'string' ? record.filename : '',
    status: normalizeStatus(record),
    progress: normalizeProgress(record.progress),
    created_at: typeof record.created_at === 'string' ? record.created_at : undefined,
    updated_at: typeof record.updated_at === 'string' ? record.updated_at : undefined,
    priority: normalizePriority(record.priority),
    username: typeof record.username === 'string' ? record.username : null
  };
};

const extractDownloadArray = (value: unknown): DownloadEntry[] => {
  const data = unwrapEnvelope<unknown>(value);
  if (Array.isArray(data)) {
    return data.map(normalizeDownloadEntry).filter((entry): entry is DownloadEntry => entry !== null);
  }
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>;
    const candidateKeys = ['items', 'downloads', 'results', 'data'];
    for (const key of candidateKeys) {
      const candidate = record[key];
      if (Array.isArray(candidate)) {
        return candidate
          .map(normalizeDownloadEntry)
          .filter((entry): entry is DownloadEntry => entry !== null);
      }
      if (candidate && typeof candidate === 'object') {
        const inner = candidate as Record<string, unknown>;
        for (const innerKey of candidateKeys) {
          const nested = inner[innerKey];
          if (Array.isArray(nested)) {
            return nested
              .map(normalizeDownloadEntry)
              .filter((entry): entry is DownloadEntry => entry !== null);
          }
        }
      }
    }
  }
  return [];
};

const withDefaultDownload = (entry: DownloadEntry | undefined, fallback: Partial<DownloadEntry> = {}): DownloadEntry => ({
  id: fallback.id ?? entry?.id ?? '',
  filename: fallback.filename ?? entry?.filename ?? '',
  status: fallback.status ?? entry?.status ?? 'queued',
  progress: fallback.progress ?? entry?.progress ?? 0,
  priority: fallback.priority ?? entry?.priority ?? 0,
  created_at: fallback.created_at ?? entry?.created_at,
  updated_at: fallback.updated_at ?? entry?.updated_at,
  username: fallback.username ?? entry?.username ?? null
});

const normalizeStats = (value: unknown): DownloadStats => {
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const entries: Record<string, number> = {};
    for (const [key, raw] of Object.entries(record)) {
      if (typeof raw === 'number') {
        entries[key] = Number.isFinite(raw) ? raw : 0;
      } else if (typeof raw === 'string') {
        const parsed = Number.parseInt(raw, 10);
        entries[key] = Number.isFinite(parsed) ? parsed : 0;
      }
    }
    if (typeof entries.failed !== 'number') {
      entries.failed = 0;
    }
    return entries as DownloadStats;
  }
  return { failed: 0 };
};

const normalizeRetryAllResponse = (value: unknown): RetryAllFailedResponse => {
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const requeued = normalizePriority(record.requeued);
    const skipped = normalizePriority(record.skipped);
    return { requeued, skipped };
  }
  return { requeued: 0, skipped: 0 };
};

export const getDownloads = async (options: FetchDownloadsOptions = {}): Promise<DownloadEntry[]> => {
  const params: Record<string, string> = {};
  if (options.includeAll) {
    params.scope = 'all';
  }
  if (typeof options.status === 'string' && options.status.length > 0 && options.status !== 'all') {
    params.status = options.status;
  }
  if (typeof options.page === 'number' && Number.isFinite(options.page)) {
    params.page = String(Math.max(1, Math.trunc(options.page)));
  } else if (typeof options.offset === 'number' && Number.isFinite(options.offset)) {
    if (typeof options.limit === 'number' && Number.isFinite(options.limit) && options.limit > 0) {
      params.page = String(Math.floor(options.offset / options.limit) + 1);
    }
  }
  if (typeof options.pageSize === 'number' && Number.isFinite(options.pageSize) && options.pageSize > 0) {
    params.page_size = String(Math.trunc(options.pageSize));
  } else if (typeof options.limit === 'number' && Number.isFinite(options.limit) && options.limit > 0) {
    params.page_size = String(Math.trunc(options.limit));
  }

  const payload = await request<unknown>({
    method: 'GET',
    url: apiUrl('/downloads'),
    params: Object.keys(params).length > 0 ? params : undefined
  });
  return extractDownloadArray(payload);
};

export const startDownload = async (payload: StartDownloadPayload): Promise<DownloadEntry> => {
  const response = await request<unknown>({
    method: 'POST',
    url: apiUrl('/download'),
    data: payload
  });
  const [first] = extractDownloadArray(response);
  return withDefaultDownload(first, { filename: '', status: 'queued', progress: 0, priority: 0 });
};

export const retryDownload = async (id: string | number): Promise<DownloadEntry> => {
  const payload = await request<unknown>({
    method: 'POST',
    url: apiUrl(`/downloads/${id}/retry`)
  });
  const [first] = extractDownloadArray(payload);
  const result = withDefaultDownload(first, { id });
  if (isDevEnvironment()) {
    console.debug('downloads.retry', { id: result.id, status: result.status });
  }
  return result;
};

export const cancelDownload = async (id: string | number): Promise<void> => {
  await request<unknown>({
    method: 'DELETE',
    url: apiUrl(`/download/${id}`)
  });
  if (isDevEnvironment()) {
    console.debug('downloads.cancel', { id });
  }
};

export const clearDownload = async (id: string | number): Promise<void> => {
  await request<unknown>({
    method: 'DELETE',
    url: apiUrl(`/downloads/${id}`)
  });
  if (isDevEnvironment()) {
    console.debug('downloads.clear', { id });
  }
};

export const updateDownloadPriority = async (id: string | number, priority: number): Promise<DownloadEntry> => {
  const payload = await request<unknown>({
    method: 'PATCH',
    url: apiUrl(`/download/${id}/priority`),
    data: { priority }
  });
  const [first] = extractDownloadArray(payload);
  return withDefaultDownload(first, { id, priority });
};

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
    url: apiUrl('/downloads/export'),
    params,
    responseType: 'blob'
  });
};

export const getDownloadStats = async (): Promise<DownloadStats> => {
  const payload = await request<unknown>({
    method: 'GET',
    url: apiUrl('/downloads/stats')
  });
  const data = unwrapEnvelope<unknown>(payload);
  return normalizeStats(data);
};

export const retryAllFailed = async (): Promise<RetryAllFailedResponse> => {
  const payload = await request<unknown>({
    method: 'POST',
    url: apiUrl('/downloads/retry-failed')
  });
  const data = unwrapEnvelope<unknown>(payload);
  const result = normalizeRetryAllResponse(data);
  if (isDevEnvironment()) {
    console.debug('downloads.retry_all', result);
  }
  return result;
};

interface UseDownloadStatsOptions {
  enabled?: boolean;
}

export const useDownloadStats = (options: UseDownloadStatsOptions = {}) =>
  useQuery<DownloadStats>({
    queryKey: [...DOWNLOAD_STATS_QUERY_KEY],
    queryFn: getDownloadStats,
    enabled: options.enabled ?? true
  });

export interface RetryDownloadVariables {
  id: string;
  filename?: string | null;
}

interface UseRetryDownloadOptions {
  onSuccess?: (data: DownloadEntry, variables: RetryDownloadVariables) => void;
  onError?: (error: unknown, variables: RetryDownloadVariables) => void;
}

export const useRetryDownload = (options: UseRetryDownloadOptions = {}) =>
  useMutation<RetryDownloadVariables, DownloadEntry>({
    mutationFn: ({ id }) => retryDownload(id),
    onSuccess: (data, variables) => {
      options.onSuccess?.(data, variables);
    },
    onError: (error, variables) => {
      options.onError?.(error, variables);
    }
  });

export interface ClearDownloadVariables {
  id: string;
  filename?: string | null;
}

interface UseClearDownloadOptions {
  onSuccess?: (variables: ClearDownloadVariables) => void;
  onError?: (error: unknown, variables: ClearDownloadVariables) => void;
}

export const useClearDownload = (options: UseClearDownloadOptions = {}) =>
  useMutation<ClearDownloadVariables, void>({
    mutationFn: ({ id }) => clearDownload(id),
    onSuccess: (_, variables) => {
      options.onSuccess?.(variables);
    },
    onError: (error, variables) => {
      options.onError?.(error, variables);
    }
  });

interface UseRetryAllFailedOptions {
  onSuccess?: (data: RetryAllFailedResponse) => void;
  onError?: (error: unknown) => void;
}

export const useRetryAllFailed = (options: UseRetryAllFailedOptions = {}) => {
  const queryClient = useQueryClient();
  const [isSupported, setIsSupported] = useState(true);

  const mutation = useMutation<void, RetryAllFailedResponse>({
    mutationFn: () => retryAllFailed(),
    onSuccess: (data) => {
      setIsSupported(true);
      queryClient.invalidateQueries({ queryKey: [...DOWNLOAD_STATS_QUERY_KEY] });
      options.onSuccess?.(data);
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        if (error.status === 404 || error.status === 405 || error.status === 501) {
          setIsSupported(false);
        }
      }
      options.onError?.(error);
    }
  });

  const mutate = useCallback(() => mutation.mutate(undefined as void), [mutation]);
  const mutateAsync = useCallback(() => mutation.mutateAsync(undefined as void), [mutation]);

  return {
    ...mutation,
    mutate,
    mutateAsync,
    isSupported
  };
};
