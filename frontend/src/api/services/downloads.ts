import { useCallback, useState } from 'react';

import { apiUrl, request } from '../client';
import type {
  ApiEnvelope,
  DownloadEntry,
  DownloadExportFilters,
  DownloadStats,
  FetchDownloadsOptions,
  RetryAllFailedResponse,
  StartDownloadPayload
} from '../types';
import { useMutation, useQuery, useQueryClient } from '../../lib/query';
import { ApiError } from '../client';
import { LIBRARY_POLL_INTERVAL_MS } from '../config';

export const DOWNLOAD_STATS_QUERY_KEY = ['downloads', 'stats'] as const;

const unwrapEnvelope = <T>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'ok' in (payload as Record<string, unknown>)) {
    const envelope = payload as ApiEnvelope<T>;
    if (!envelope.ok) {
      const code = envelope.error?.code ?? 'UNKNOWN_ERROR';
      const message = envelope.error?.message ?? code;
      throw new ApiError({
        code,
        message,
        status: 400,
        details: envelope,
        body: envelope
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
    params.page = String(options.page);
  }
  if (typeof options.pageSize === 'number' && Number.isFinite(options.pageSize)) {
    params.page_size = String(options.pageSize);
  }
  if (typeof options.limit === 'number' && Number.isFinite(options.limit)) {
    params.limit = String(options.limit);
  }
  if (typeof options.offset === 'number' && Number.isFinite(options.offset)) {
    params.offset = String(options.offset);
  }
  const payload = await request<unknown>({ method: 'GET', url: apiUrl('/downloads'), params });
  return extractDownloadArray(payload);
};

export const startDownload = async (payload: StartDownloadPayload): Promise<DownloadEntry> => {
  const response = await request<unknown>({ method: 'POST', url: apiUrl('/downloads/start'), data: payload });
  return withDefaultDownload(normalizeDownloadEntry(response) ?? undefined, {
    filename: '',
    status: 'queued',
    progress: 0
  });
};

export const retryDownload = async (id: string | number): Promise<DownloadEntry> => {
  const response = await request<unknown>({ method: 'POST', url: apiUrl(`/downloads/${id}/retry`) });
  return withDefaultDownload(normalizeDownloadEntry(response) ?? undefined, { id });
};

export const cancelDownload = async (id: string | number): Promise<void> => {
  await request<void>({ method: 'POST', url: apiUrl(`/downloads/${id}/cancel`), responseType: 'void' });
};

export const clearDownload = async (id: string | number): Promise<void> => {
  await request<void>({ method: 'POST', url: apiUrl(`/downloads/${id}/clear`), responseType: 'void' });
};

export const updateDownloadPriority = async (id: string | number, priority: number): Promise<DownloadEntry> => {
  const response = await request<unknown>({
    method: 'POST',
    url: apiUrl(`/downloads/${id}/priority`),
    data: { priority }
  });
  return withDefaultDownload(normalizeDownloadEntry(response) ?? undefined, { id, priority });
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
  const payload = await request<unknown>({ method: 'GET', url: apiUrl('/downloads/stats') });
  const data = unwrapEnvelope<unknown>(payload);
  return normalizeStats(data);
};

export const retryAllFailed = async (): Promise<RetryAllFailedResponse> => {
  const payload = await request<unknown>({ method: 'POST', url: apiUrl('/downloads/retry-failed') });
  const data = unwrapEnvelope<unknown>(payload);
  return normalizeRetryAllResponse(data);
};

interface UseDownloadStatsOptions {
  enabled?: boolean;
}

export const useDownloadStats = (options: UseDownloadStatsOptions = {}) =>
  useQuery<DownloadStats>({
    queryKey: [...DOWNLOAD_STATS_QUERY_KEY],
    queryFn: getDownloadStats,
    enabled: options.enabled
  });

interface UseRetryDownloadOptions {
  onSuccess?: (entry: DownloadEntry, variables: { id: string | number; filename: string }) => void;
  onError?: (error: unknown, variables: { id: string | number; filename: string }) => void;
}

export const useRetryDownload = (options: UseRetryDownloadOptions = {}) =>
  useMutation({
    mutationFn: async ({ id }: { id: string | number; filename: string }) => retryDownload(id),
    onSuccess: options.onSuccess,
    onError: options.onError
  });

export interface ClearDownloadInput {
  id: string | number;
  filename?: string;
}

interface UseClearDownloadOptions {
  onSuccess?: (result: ClearDownloadInput, variables: ClearDownloadInput) => void;
  onError?: (error: unknown, variables: ClearDownloadInput) => void;
}

export const useClearDownload = (options: UseClearDownloadOptions = {}) =>
  useMutation<ClearDownloadInput, ClearDownloadInput>({
    mutationFn: async (variables) => {
      await clearDownload(variables.id);
      return variables;
    },
    onSuccess: (result, variables) => {
      options.onSuccess?.(result, variables);
    },
    onError: (error, variables) => {
      options.onError?.(error, variables);
    }
  });

interface UseRetryAllFailedOptions {
  onSuccess?: (response: RetryAllFailedResponse) => void;
  onError?: (error: unknown) => void;
}

export const useRetryAllFailed = (options: UseRetryAllFailedOptions = {}) => {
  const queryClient = useQueryClient();
  const [isPending, setIsPending] = useState(false);

  const mutateAsync = useCallback(async () => {
    setIsPending(true);
    try {
      const result = await retryAllFailed();
      await queryClient.invalidateQueries({ queryKey: [...DOWNLOAD_STATS_QUERY_KEY] });
      options.onSuccess?.(result);
      return result;
    } catch (error) {
      options.onError?.(error);
      throw error;
    } finally {
      setIsPending(false);
    }
  }, [options, queryClient]);

  return {
    mutateAsync,
    isPending
  };
};

export { LIBRARY_POLL_INTERVAL_MS };
