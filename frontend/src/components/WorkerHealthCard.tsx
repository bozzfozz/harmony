import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { cn } from '../lib/utils';
import type { WorkerStatus } from '../lib/api';

export interface WorkerHealthCardProps {
  workerName: string;
  lastSeen?: string | null;
  queueSize?: number | Record<string, number | string> | string | null;
  status?: WorkerStatus;
}

const STATUS_STYLES: Record<string, { badge: string; dot: string }> = {
  running: {
    badge:
      'border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400',
    dot: 'bg-emerald-500'
  },
  stopped: {
    badge:
      'border-red-500/40 bg-red-500/10 text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-400',
    dot: 'bg-red-500'
  },
  stale: {
    badge:
      'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400',
    dot: 'bg-amber-400'
  },
  blocked: {
    badge:
      'border-amber-500/60 bg-amber-500/15 text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/20 dark:text-amber-300',
    dot: 'bg-amber-500'
  },
  default: {
    badge: 'border-border bg-muted text-muted-foreground',
    dot: 'bg-muted-foreground'
  }
};

const formatWorkerName = (name: string) =>
  name
    .replace(/[_-]+/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');

const formatStatus = (status?: WorkerStatus) => {
  if (!status) {
    return 'Unbekannt';
  }
  return status
    .toString()
    .split(/[_-]+/g)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
};

const formatQueueSize = (
  queueSize?: number | Record<string, number | string> | string | null
) => {
  if (queueSize === null || typeof queueSize === 'undefined') {
    return '—';
  }
  if (typeof queueSize === 'number') {
    return queueSize.toString();
  }
  if (typeof queueSize === 'string') {
    return queueSize.trim() === '' ? '—' : queueSize;
  }
  const entries = Object.entries(queueSize)
    .filter(([, value]) => value !== null && typeof value !== 'undefined')
    .map(([key, value]) => `${key}: ${value}`);
  if (entries.length === 0) {
    return '—';
  }
  return entries.join(' • ');
};

const RELATIVE_TIME_FORMATS = [
  { limit: 60 * 1000, divisor: 1000, suffix: 's' },
  { limit: 60 * 60 * 1000, divisor: 60 * 1000, suffix: 'm' },
  { limit: 24 * 60 * 60 * 1000, divisor: 60 * 60 * 1000, suffix: 'h' },
  { limit: 7 * 24 * 60 * 60 * 1000, divisor: 24 * 60 * 60 * 1000, suffix: 'd' },
  { limit: 30 * 24 * 60 * 60 * 1000, divisor: 7 * 24 * 60 * 60 * 1000, suffix: 'w' },
  { limit: Number.POSITIVE_INFINITY, divisor: 30 * 24 * 60 * 60 * 1000, suffix: 'mo' }
];

const formatLastSeen = (timestamp?: string | null) => {
  if (!timestamp) {
    return 'Keine Daten';
  }
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return 'Keine Daten';
  }
  const diff = Date.now() - parsed.getTime();
  const absDiff = Math.abs(diff);
  if (absDiff < 5000) {
    return 'gerade eben';
  }
  for (const { limit, divisor, suffix } of RELATIVE_TIME_FORMATS) {
    if (absDiff < limit) {
      const value = Math.max(1, Math.round(absDiff / divisor));
      return diff >= 0 ? `vor ${value}${suffix}` : `in ${value}${suffix}`;
    }
  }
  return '—';
};

const WorkerHealthCard = ({ workerName, lastSeen, queueSize, status }: WorkerHealthCardProps) => {
  const normalizedStatus = (status ?? '').toString().toLowerCase();
  const style = STATUS_STYLES[normalizedStatus] ?? STATUS_STYLES.default;

  return (
    <Card data-testid={`worker-card-${workerName}`}>
      <CardHeader className="space-y-2">
        <CardTitle className="text-base font-semibold">{formatWorkerName(workerName)}</CardTitle>
        <span
          className={cn(
            'inline-flex w-fit items-center gap-2 rounded-full border px-2 py-0.5 text-xs font-semibold',
            style.badge
          )}
        >
          <span className={cn('h-2 w-2 rounded-full', style.dot)} aria-hidden />
          <span className="capitalize">{formatStatus(status)}</span>
        </span>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <span>Queue</span>
          <span className="font-medium text-muted-foreground">{formatQueueSize(queueSize)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Zuletzt gesehen</span>
          <span className="font-medium text-muted-foreground">{formatLastSeen(lastSeen)}</span>
        </div>
      </CardContent>
    </Card>
  );
};

export default WorkerHealthCard;

export { formatLastSeen, formatQueueSize, formatStatus, formatWorkerName };
