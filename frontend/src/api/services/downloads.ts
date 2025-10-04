import { apiUrl, request } from '../client';
import type {
  ApiEnvelope,
  DownloadEntry,
  DownloadExportFilters,
  FetchDownloadsOptions,
  StartDownloadPayload,
  DownloadFilePayload
} from '../types';
import { useMutation, useQuery } from '../../lib/query';
import { ApiError } from '../client';
import { LIBRARY_POLL_INTERVAL_MS } from '../config';

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

const normalizeDownloadFilePayload = (file: DownloadFilePayload): DownloadFilePayload | null => {
  const normalized: DownloadFilePayload = { ...file };

  const rawFilename = typeof file.filename === 'string' ? file.filename.trim() : '';
  const rawName = typeof file.name === 'string' ? file.name.trim() : '';
  const rawSource = typeof file.source === 'string' ? file.source.trim() : '';

  if (rawFilename) {
    normalized.filename = rawFilename;
  } else {
    delete normalized.filename;
  }

  if (rawName) {
    normalized.name = rawName;
  } else if (rawFilename) {
    normalized.name = rawFilename;
  } else {
    delete normalized.name;
  }

  if (rawSource) {
    normalized.source = rawSource;
  } else {
    delete normalized.source;
  }

  if (typeof file.priority === 'number' && Number.isFinite(file.priority)) {
    normalized.priority = Math.round(file.priority);
  } else {
    delete normalized.priority;
  }

  if (!normalized.filename && !normalized.name) {
    return null;
  }

  return normalized;
};

const normalizeStartDownloadPayload = (payload: StartDownloadPayload): StartDownloadPayload => {
  const username = typeof payload.username === 'string' ? payload.username.trim() : '';
  const files = Array.isArray(payload.files) ? payload.files : [];

  const normalizedFiles = files
    .map((file) => normalizeDownloadFilePayload(file))
    .filter((file): file is DownloadFilePayload => file !== null);

  return {
    username,
    files: normalizedFiles
  };
};

export const getDownloads = async (options: FetchDownloadsOptions = {}): Promise<DownloadEntry[]> => {
  const params: Record<string, string> = {};
  if (options.includeAll) {
    params.all = 'true';
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
  const requestPayload = normalizeStartDownloadPayload(payload);
  const response = await request<unknown>({ method: 'POST', url: apiUrl('/download'), data: requestPayload });
  return withDefaultDownload(normalizeDownloadEntry(response) ?? undefined, {
    filename: '',
    status: 'queued',
    progress: 0
  });
};

export const retryDownload = async (id: string | number): Promise<DownloadEntry> => {
  const response = await request<unknown>({ method: 'POST', url: apiUrl(`/download/${id}/retry`) });
  return withDefaultDownload(normalizeDownloadEntry(response) ?? undefined, { id });
};

export const cancelDownload = async (id: string | number): Promise<void> => {
  await request<void>({ method: 'DELETE', url: apiUrl(`/download/${id}`), responseType: 'void' });
};

export const updateDownloadPriority = async (id: string | number, priority: number): Promise<DownloadEntry> => {
  const response = await request<unknown>({
    method: 'PATCH',
    url: apiUrl(`/download/${id}/priority`),
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

export { LIBRARY_POLL_INTERVAL_MS };
