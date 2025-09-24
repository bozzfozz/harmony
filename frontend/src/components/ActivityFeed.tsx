import { useEffect, useMemo, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { useToast } from '../hooks/useToast';
import { fetchActivityFeed, ActivityItem, ActivityStatus, ActivityType } from '../lib/api';
import { useQuery } from '../lib/query';
import { cn } from '../lib/utils';

const ACTIVITY_TYPE_LABELS = {
  sync: 'Synchronisierung',
  search: 'Suche',
  download: 'Download',
  metadata: 'Metadaten'
} as const satisfies Record<string, string>;

type KnownActivityType = keyof typeof ACTIVITY_TYPE_LABELS;

const STATUS_STYLES = {
  completed:
    'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  running: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200',
  queued: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  failed: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200',
  cancelled: 'bg-slate-100 text-slate-800 dark:bg-slate-900/40 dark:text-slate-200'
} as const satisfies Record<string, string>;

const STATUS_LABELS = {
  completed: 'Abgeschlossen',
  running: 'Laufend',
  queued: 'Wartend',
  failed: 'Fehlgeschlagen',
  cancelled: 'Abgebrochen'
} as const satisfies Record<string, string>;

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
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Zeitpunkt</TableHead>
                  <TableHead>Typ</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((item) => (
                  <TableRow key={`${item.timestamp}-${item.type}-${item.status}`}>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {formatTimestamp(item.timestamp)}
                    </TableCell>
                    <TableCell className="text-sm font-medium">{getTypeLabel(item.type)}</TableCell>
                    <TableCell>
                      {(() => {
                        const { label, className } = getStatusMeta(item.status);
                        return (
                          <span
                            className={cn(
                              'inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold',
                              className
                            )}
                          >
                            {label}
                          </span>
                        );
                      })()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default ActivityFeed;
