import { ReactNode, useEffect, useMemo, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { useToast } from '../hooks/useToast';
import { fetchActivityFeed, ActivityItem, ActivityStatus, ActivityType } from '../lib/api';
import { useQuery } from '../lib/query';
import { cn } from '../lib/utils';

const ACTIVITY_TYPE_LABELS = {
  sync: 'Synchronisierung',
  autosync: 'AutoSync',
  search: 'Suche',
  download: 'Download',
  metadata: 'Metadaten',
  worker: 'Worker'
} as const satisfies Record<string, string>;

type KnownActivityType = keyof typeof ACTIVITY_TYPE_LABELS;

const ACTIVITY_TYPE_ICONS = {
  sync: '🔄',
  autosync: '🤖',
  search: '🔍',
  download: '⬇',
  metadata: '🗂',
  worker: '🛠️'
} as const satisfies Record<string, string>;

const STATUS_STYLES = {
  completed:
    'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  partial: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  running: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200',
  queued: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  failed: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200',
  cancelled: 'bg-slate-100 text-slate-800 dark:bg-slate-900/40 dark:text-slate-200',
  started: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  stopped: 'bg-slate-100 text-slate-800 dark:bg-slate-900/40 dark:text-slate-200',
  stale: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  restarted: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200'
} as const satisfies Record<string, string>;

const STATUS_LABELS = {
  completed: 'Abgeschlossen',
  partial: 'Teilweise',
  running: 'Laufend',
  queued: 'Wartend',
  failed: 'Fehlgeschlagen',
  cancelled: 'Abgebrochen',
  started: 'Gestartet',
  stopped: 'Gestoppt',
  stale: 'Veraltet',
  restarted: 'Neu gestartet'
} as const satisfies Record<string, string>;

const WORKER_STATUS_ICONS = {
  started: '▶️',
  stopped: '⏹',
  stale: '⚠️',
  restarted: '🔄'
} as const;

type WorkerStatus = keyof typeof WORKER_STATUS_ICONS;

const isWorkerStatus = (status: string): status is WorkerStatus =>
  Object.prototype.hasOwnProperty.call(WORKER_STATUS_ICONS, status);

type KnownStatus = keyof typeof STATUS_STYLES;

const isKnownActivityType = (type: ActivityType): type is KnownActivityType =>
  Object.prototype.hasOwnProperty.call(ACTIVITY_TYPE_LABELS, type);

const isKnownStatus = (status: string): status is KnownStatus =>
  Object.prototype.hasOwnProperty.call(STATUS_STYLES, status);

const prettify = (value: string) => {
  const normalized = value.replace(/[_-]+/g, ' ').trim();
  if (!normalized) {
    return value;
  }
  return normalized
    .split(' ')
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
};

const getTypeLabel = (type: ActivityType) =>
  isKnownActivityType(type) ? ACTIVITY_TYPE_LABELS[type] : prettify(type);

const getStatusMeta = (status: ActivityStatus) => {
  const normalized = status.toLowerCase();
  if (normalized.endsWith('_blocked')) {
    const blockedStyle = STATUS_STYLES.failed;
    return {
      label: 'Blockiert',
      className: blockedStyle,
    };
  }
  if (isKnownStatus(normalized)) {
    return {
      label: STATUS_LABELS[normalized],
      className: STATUS_STYLES[normalized]
    };
  }
  return {
    label: prettify(status),
    className: 'bg-muted text-muted-foreground'
  };
};

const parseTimestamp = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 0;
  }
  return date.getTime();
};

const formatTimestamp = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'short',
    timeStyle: 'medium'
  }).format(date);
};

const toRecord = (value: unknown): Record<string, unknown> | null => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
};

const toStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map((entry) => {
        if (typeof entry === 'string') {
          return entry;
        }
        if (entry && typeof entry === 'object') {
          const record = entry as Record<string, unknown>;
          if (typeof record.source === 'string') {
            return record.source;
          }
          if (typeof record.name === 'string') {
            return record.name;
          }
        }
        return String(entry);
      })
      .filter((entry) => entry.length > 0);
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([, enabled]) => Boolean(enabled))
      .map(([key]) => key);
  }
  if (typeof value === 'string') {
    return [value];
  }
  return [];
};

const extractErrors = (value: unknown): string[] => {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value
      .map((entry) => {
        if (typeof entry === 'string') {
          return entry;
        }
        if (entry && typeof entry === 'object') {
          const record = entry as Record<string, unknown>;
          if (typeof record.message === 'string' && typeof record.source === 'string') {
            return `${prettify(String(record.source))}: ${record.message}`;
          }
          if (typeof record.message === 'string') {
            return record.message;
          }
          return Object.entries(record)
            .map(([key, detail]) => `${prettify(key)}: ${String(detail)}`)
            .join(', ');
        }
        return String(entry);
      })
      .filter(Boolean);
  }
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, detail]) => `${prettify(key)}: ${String(detail)}`)
      .filter(Boolean);
  }
  if (typeof value === 'string') {
    return [value];
  }
  return [];
};

const COUNTER_EXCLUDE = new Set(['sources', 'query', 'matches', 'results', 'metrics', 'counters']);

const extractCounterEntries = (details: Record<string, unknown>): Array<[string, number]> => {
  const counters =
    toRecord((details as { counters?: unknown }).counters) ??
    toRecord((details as { metrics?: unknown }).metrics);
  const record: Record<string, unknown> =
    counters ??
    (Object.fromEntries(
      Object.entries(details).filter(([key, value]) => typeof value === 'number' && !COUNTER_EXCLUDE.has(key))
    ) as Record<string, unknown>);
  return Object.entries(record)
    .filter(([, value]) => typeof value === 'number')
    .map(([key, value]) => [key, value as number]);
};

const extractMatchEntries = (details: Record<string, unknown>): Array<[string, number]> => {
  const matchesRecord =
    toRecord((details as { matches?: unknown }).matches) ??
    toRecord((details as { results?: unknown }).results) ??
    (Array.isArray((details as { matches?: unknown }).matches)
      ? Object.fromEntries(
          ((details as { matches?: unknown[] }).matches as unknown[])
            .map((entry) => {
              if (entry && typeof entry === 'object') {
                const record = entry as Record<string, unknown>;
                if (typeof record.source === 'string' && typeof record.count === 'number') {
                  return [record.source, record.count];
                }
              }
              return null;
            })
            .filter((entry): entry is [string, number] => Array.isArray(entry))
        )
      : null);
  if (!matchesRecord) {
    return [];
  }
  return Object.entries(matchesRecord as Record<string, unknown>)
    .filter(([, value]) => typeof value === 'number')
    .map(([key, value]) => [key, value as number]);
};

const renderActivityDetails = (item: ActivityItem): ReactNode => {
  if (!item.details) {
    return null;
  }

  if (item.type === 'worker') {
    const details = item.details as Record<string, unknown>;
    const blocks: ReactNode[] = [];
    const workerName = typeof details.worker === 'string' ? details.worker : undefined;
    const previousStatus = typeof details.previous_status === 'string' ? details.previous_status : undefined;
    const reason = typeof details.reason === 'string' ? details.reason : undefined;
    const rawTimestamp = typeof details.timestamp === 'string' ? details.timestamp : item.timestamp;

    if (workerName) {
      blocks.push(
        <p key="worker" className="text-sm">
          <span className="font-medium text-foreground">Worker:</span>{' '}
          <span className="text-muted-foreground">{prettify(workerName)}</span>
        </p>
      );
    }

    blocks.push(
      <p key="event-time" className="text-sm">
        <span className="font-medium text-foreground">Eventzeit:</span>{' '}
        <span className="text-muted-foreground">{formatTimestamp(String(rawTimestamp))}</span>
      </p>
    );

    if (previousStatus) {
      blocks.push(
        <p key="previous-status" className="text-sm">
          <span className="font-medium text-foreground">Vorheriger Status:</span>{' '}
          <span className="text-muted-foreground">{prettify(previousStatus)}</span>
        </p>
      );
    }

    if (reason) {
      blocks.push(
        <p key="reason" className="text-sm">
          <span className="font-medium text-foreground">Hinweis:</span>{' '}
          <span className="text-muted-foreground">{reason}</span>
        </p>
      );
    }

    if (item.status === 'stale') {
      const lastSeen = typeof details.last_seen === 'string' ? details.last_seen : undefined;
      const threshold = typeof details.threshold_seconds === 'number' ? details.threshold_seconds : undefined;
      const elapsed = typeof details.elapsed_seconds === 'number' ? details.elapsed_seconds : undefined;
      const parts: string[] = [];
      if (lastSeen) {
        parts.push(`Heartbeat: ${formatTimestamp(lastSeen)}`);
      }
      if (elapsed !== undefined) {
        parts.push(`Δ ${Math.round(elapsed)}s`);
      }
      if (threshold !== undefined) {
        parts.push(`Schwelle ${threshold}s`);
      }
      if (parts.length > 0) {
        blocks.push(
          <p key="stale-info" className="text-sm">
            <span className="font-medium text-foreground">Überwachung:</span>{' '}
            <span className="text-muted-foreground">{parts.join(' · ')}</span>
          </p>
        );
      }
    }

    if (!blocks.length) {
      return null;
    }

    return <div className="space-y-2">{blocks}</div>;
  }

  const details = item.details;
  const blocks: ReactNode[] = [];

  const errors = extractErrors((details as { errors?: unknown }).errors);

  if (item.type === 'sync') {
    const sources = toStringArray((details as { sources?: unknown }).sources);
    if (sources.length > 0) {
      blocks.push(
        <p key="sources" className="text-sm">
          <span className="font-medium text-foreground">Quellen:</span>{' '}
          <span className="text-muted-foreground">{sources.map(prettify).join(', ')}</span>
        </p>
      );
    }

    const counters = extractCounterEntries(details);
    if (counters.length > 0) {
      blocks.push(
        <div key="counters" className="text-sm">
          <p className="font-medium text-foreground">Kennzahlen</p>
          <ul className="mt-1 space-y-1 text-muted-foreground">
            {counters.map(([key, value]) => (
              <li key={key}>
                {prettify(key)}: <span className="font-medium text-foreground">{value}</span>
              </li>
            ))}
          </ul>
        </div>
      );
    }
  }

  if (item.type === 'search') {
    const query = (details as { query?: unknown }).query;
    if (typeof query === 'string') {
      blocks.push(
        <p key="query" className="text-sm">
          <span className="font-medium text-foreground">Suchanfrage:</span>{' '}
          <span className="text-muted-foreground">{query}</span>
        </p>
      );
    }

    const matches = extractMatchEntries(details);
    if (matches.length > 0) {
      blocks.push(
        <div key="matches" className="text-sm">
          <p className="font-medium text-foreground">Treffer pro Quelle</p>
          <ul className="mt-1 space-y-1 text-muted-foreground">
            {matches.map(([source, count]) => (
              <li key={source}>
                {prettify(source)}: <span className="font-medium text-foreground">{count}</span>
              </li>
            ))}
          </ul>
        </div>
      );
    }
  }

  if (!blocks.length && errors.length === 0 && Object.keys(details).length > 0) {
    blocks.push(
      <pre key="raw" className="overflow-x-auto rounded-md bg-muted p-3 text-xs text-muted-foreground">
        {JSON.stringify(details, null, 2)}
      </pre>
    );
  }

  if (errors.length > 0) {
    blocks.push(
      <div
        key="errors"
        className="inline-flex items-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700 shadow-sm dark:border-rose-900/60 dark:bg-rose-900/30 dark:text-rose-200"
        title={errors.join('\n')}
      >
        ⚠️ Fehlerdetails ({errors.length})
      </div>
    );
  }

  if (!blocks.length) {
    return null;
  }

  return <div className="space-y-3">{blocks}</div>;
};

const renderStatusBadge = (status: ActivityStatus) => {
  const { label, className } = getStatusMeta(status);
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full px-2 py-1 text-xs font-semibold uppercase tracking-wide',
        className
      )}
    >
      {label}
    </span>
  );
};

const renderActivitySummary = (item: ActivityItem) => {
  const normalizedStatus = String(item.status).toLowerCase();
  let icon: string = ACTIVITY_TYPE_ICONS[item.type as keyof typeof ACTIVITY_TYPE_ICONS] ?? 'ℹ️';
  let title = getTypeLabel(item.type);
  const isBlockedStatus = normalizedStatus.endsWith('_blocked');

  if (item.type === 'worker') {
    const workerDetails = item.details as { worker?: unknown } | undefined;
    const workerName =
      workerDetails && typeof workerDetails.worker === 'string' ? workerDetails.worker : undefined;
    if (isWorkerStatus(normalizedStatus)) {
      icon = WORKER_STATUS_ICONS[normalizedStatus];
    } else {
      icon = '🛠️';
    }
    title = workerName ? `Worker ${prettify(workerName)}` : getTypeLabel(item.type);
  } else if (isBlockedStatus) {
    icon = '⛔';
  }

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 text-left">
        <span aria-hidden="true" className="text-lg">
          {icon}
        </span>
        <div className="space-y-1">
          <p className="text-sm font-medium leading-none text-foreground">{title}</p>
          <p className="text-xs text-muted-foreground">{formatTimestamp(item.timestamp)}</p>
        </div>
      </div>
      {renderStatusBadge(item.status)}
    </div>
  );
};

const ActivityFeed = () => {
  const { toast } = useToast();
  const emptyToastShownRef = useRef(false);

  const { data, isLoading, isError } = useQuery<ActivityItem[]>({
    queryKey: ['activity-feed'],
    queryFn: fetchActivityFeed,
    refetchInterval: 10000,
    onError: () =>
      toast({
        title: 'Aktivitäten konnten nicht geladen werden',
        description: 'Bitte prüfen Sie die Backend-Verbindung.',
        variant: 'destructive'
      })
  });

  useEffect(() => {
    if (!data) {
      return;
    }
    if (data.length === 0) {
      if (!emptyToastShownRef.current) {
        toast({
          title: 'Keine Activity-Daten',
          description: 'Es liegen noch keine Aktivitäten im Feed vor.'
        });
        emptyToastShownRef.current = true;
      }
    } else {
      emptyToastShownRef.current = false;
    }
  }, [data, toast]);

  const rows = useMemo(() => {
    if (!data) {
      return [] as ActivityItem[];
    }
    return [...data].sort((a, b) => parseTimestamp(b.timestamp) - parseTimestamp(a.timestamp));
  }, [data]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Activity Feed</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" aria-label="Lade Aktivitäten" />
          </div>
        ) : isError ? (
          <p className="text-sm text-destructive">
            Der Aktivitätsfeed ist derzeit nicht verfügbar.
          </p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Keine Aktivitäten vorhanden.</p>
        ) : (
          <div className="space-y-3">
            {rows.map((item) => {
              const detailsContent = renderActivityDetails(item);
              const key = `${item.timestamp}-${item.type}-${item.status}`;
              if (!detailsContent) {
                return (
                  <div
                    key={key}
                    className="rounded-lg border bg-card px-4 py-3 text-card-foreground shadow-sm"
                    data-testid="activity-entry"
                  >
                    {renderActivitySummary(item)}
                  </div>
                );
              }
              return (
                <details
                  key={key}
                  className="group rounded-lg border bg-card text-card-foreground shadow-sm"
                  data-testid="activity-entry"
                >
                  <summary className="flex cursor-pointer select-none items-center justify-between gap-4 px-4 py-3 text-sm font-medium outline-none transition hover:bg-muted/60 focus-visible:bg-muted/80 [&::-webkit-details-marker]:hidden">
                    {renderActivitySummary(item)}
                  </summary>
                  <div className="border-t px-4 py-3 text-sm text-muted-foreground">{detailsContent}</div>
                </details>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default ActivityFeed;
