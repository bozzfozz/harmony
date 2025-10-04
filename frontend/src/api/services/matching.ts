import { apiUrl, request } from '../client';
import {
  getSettings,
  getSystemStatus
} from './system';
import type {
  ActivityItem,
  SettingsResponse,
  SystemStatusResponse,
  WorkerHealth,
  WorkerStatus
} from '../types';

export interface MatchingMetrics {
  lastAverageConfidence?: number | null;
  lastDiscarded?: number | null;
  savedTotal?: number | null;
  discardedTotal?: number | null;
}

export interface MatchingBatchEvent {
  timestamp: string;
  stored?: number;
  discarded?: number;
  averageConfidence?: number;
  jobId?: string;
  jobType?: string;
}

export interface MatchingWorkerSummary {
  status?: WorkerStatus;
  lastSeen?: string | null;
  queueSize?: number | null;
  rawQueueSize?: WorkerHealth['queue_size'];
}

export interface MatchingOverview {
  worker: MatchingWorkerSummary;
  metrics: MatchingMetrics;
  events: MatchingBatchEvent[];
}

const METRIC_KEYS = {
  average: 'metrics.matching.last_average_confidence',
  lastDiscarded: 'metrics.matching.last_discarded',
  savedTotal: 'metrics.matching.saved_total',
  discardedTotal: 'metrics.matching.discarded_total'
} as const;

type ActivityResponse = ActivityItem[] | { items?: ActivityItem[] } | unknown;

const parseNumber = (value: unknown): number | null | undefined => {
  if (value === null || value === undefined) {
    return undefined;
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (trimmed === '') {
      return undefined;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

const parseQueueSize = (
  value: WorkerHealth['queue_size']
): { normalized: number | null; raw: WorkerHealth['queue_size'] } => {
  if (value === null || value === undefined) {
    return { normalized: null, raw: value };
  }
  if (typeof value === 'number') {
    return { normalized: Number.isFinite(value) ? value : null, raw: value };
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return { normalized: Number.isFinite(parsed) ? parsed : null, raw: value };
  }
  if (typeof value === 'object') {
    const entries = Object.values(value ?? {});
    for (const entry of entries) {
      const parsed = parseNumber(entry);
      if (typeof parsed === 'number') {
        return { normalized: parsed, raw: value };
      }
    }
    return { normalized: null, raw: value };
  }
  return { normalized: null, raw: value };
};

const parseMetrics = (settings: SettingsResponse['settings']): MatchingMetrics => ({
  lastAverageConfidence: parseNumber(settings[METRIC_KEYS.average]),
  lastDiscarded: parseNumber(settings[METRIC_KEYS.lastDiscarded]),
  savedTotal: parseNumber(settings[METRIC_KEYS.savedTotal]),
  discardedTotal: parseNumber(settings[METRIC_KEYS.discardedTotal])
});

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
      console.warn('Failed to parse matching activity details', error);
    }
  }
  return undefined;
};

const normalizeActivityItem = (entry: unknown): MatchingBatchEvent | null => {
  if (!entry || typeof entry !== 'object') {
    return null;
  }
  const record = entry as Record<string, unknown>;
  if (typeof record.timestamp !== 'string') {
    return null;
  }
  const details = parseActivityDetails(record.details);
  return {
    timestamp: record.timestamp,
    stored: parseNumber(details?.stored),
    discarded: parseNumber(details?.discarded),
    averageConfidence: parseNumber(details?.average_confidence),
    jobId: typeof details?.job_id === 'string' ? details?.job_id : undefined,
    jobType: typeof details?.job_type === 'string' ? details?.job_type : undefined
  };
};

const fetchMatchingActivity = async (): Promise<MatchingBatchEvent[]> => {
  const payload = await request<ActivityResponse>({
    method: 'GET',
    url: apiUrl('/activity'),
    params: { type: 'metadata', status: 'matching_batch', limit: 20 }
  });

  const normalize = (items: unknown[]): MatchingBatchEvent[] =>
    items
      .map(normalizeActivityItem)
      .filter((item): item is MatchingBatchEvent => item !== null)
      .sort((a, b) => (a.timestamp < b.timestamp ? 1 : a.timestamp > b.timestamp ? -1 : 0));

  if (Array.isArray(payload)) {
    return normalize(payload);
  }
  if (payload && typeof payload === 'object' && Array.isArray((payload as { items?: unknown[] }).items)) {
    return normalize((payload as { items: unknown[] }).items);
  }
  return [];
};

const extractWorkerSummary = (status: SystemStatusResponse): MatchingWorkerSummary => {
  const worker = status.workers?.matching;
  if (!worker) {
    return { status: undefined, lastSeen: undefined, queueSize: null, rawQueueSize: undefined };
  }
  const { normalized, raw } = parseQueueSize(worker.queue_size);
  return {
    status: worker.status,
    lastSeen: worker.last_seen,
    queueSize: normalized ?? null,
    rawQueueSize: raw
  };
};

export const getMatchingOverview = async (): Promise<MatchingOverview> => {
  const [systemStatus, settings, activity] = await Promise.all([
    getSystemStatus(),
    getSettings(),
    fetchMatchingActivity()
  ]);

  return {
    worker: extractWorkerSummary(systemStatus),
    metrics: parseMetrics(settings.settings ?? {}),
    events: activity
  };
};

export type { MatchingOverview as MatchingOverviewResponse };
