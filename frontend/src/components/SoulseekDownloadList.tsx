import { Loader2 } from 'lucide-react';

import StatusBadge from './StatusBadge';
import { Progress } from './ui/progress';
import { Button } from './ui/shadcn';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import type { NormalizedSoulseekDownload } from '../api/services/soulseek';
import { mapProgressToPercent } from '../lib/utils';

const formatStateLabel = (state: string): string => {
  const normalized = state.toLowerCase();
  const labels: Record<string, string> = {
    pending: 'Wartend',
    queued: 'Wartend',
    in_progress: 'Läuft',
    downloading: 'Läuft',
    completed: 'Abgeschlossen',
    failed: 'Fehlgeschlagen',
    dead_letter: 'Wartet auf Eingriff'
  };
  return labels[normalized] ?? state.charAt(0).toUpperCase() + state.slice(1);
};

const formatTimestamp = (value: string | null): string | null => {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleString();
};

const formatPriority = (value: number | null): string => {
  if (value === null || Number.isNaN(value)) {
    return '–';
  }
  return `${value}`;
};

const formatRetryCount = (value: number): string => {
  if (!Number.isFinite(value) || value <= 0) {
    return 'Keine Retries';
  }
  if (value === 1) {
    return '1 Retry';
  }
  return `${value} Retries`;
};

export interface SoulseekDownloadListProps {
  downloads?: NormalizedSoulseekDownload[];
  isLoading: boolean;
  isError: boolean;
  onRetryFetch?: () => void;
  onRetryDownload?: (download: NormalizedSoulseekDownload) => void;
  retryingDownloadId?: string | null;
  isRetryPending?: boolean;
  retryableStates?: readonly string[];
}

const SoulseekDownloadList = ({
  downloads,
  isLoading,
  isError,
  onRetryFetch,
  onRetryDownload,
  retryingDownloadId,
  isRetryPending = false,
  retryableStates
}: SoulseekDownloadListProps) => {
  const normalizedRetryableStates = new Set(
    (retryableStates && retryableStates.length > 0 ? retryableStates : ['failed']).map((state) =>
      state.toLowerCase()
    )
  );

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Downloads werden geladen …</p>;
  }

  if (isError) {
    return (
      <div className="flex items-center justify-between gap-4 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-900/20 dark:text-rose-200">
        <span>Downloads konnten nicht geladen werden.</span>
        {onRetryFetch ? (
          <Button variant="outline" size="sm" onClick={onRetryFetch}>
            Erneut versuchen
          </Button>
        ) : null}
      </div>
    );
  }

  if (!downloads || downloads.length === 0) {
    return <p className="text-sm text-muted-foreground">Aktuell sind keine Downloads aktiv.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Datei</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Fortschritt</TableHead>
          <TableHead>Benutzer</TableHead>
          <TableHead>Priorität / Retries</TableHead>
          <TableHead>Zeitstempel</TableHead>
          <TableHead>Aktionen</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {downloads.map((download, index) => {
          const progressValue =
            download.progress === null || Number.isNaN(download.progress)
              ? null
              : mapProgressToPercent(download.progress);
          const rowKey = download.id ?? `${download.filename ?? 'download'}-${index}`;
          const normalizedState = download.state.toLowerCase();
          const normalizedId = typeof download.id === 'string' ? download.id.trim() : null;
          const hasIdentifier = Boolean(normalizedId);
          const isDeadLetter = normalizedState === 'dead_letter';
          const canRetry =
            Boolean(onRetryDownload) &&
            hasIdentifier &&
            !isDeadLetter &&
            normalizedRetryableStates.has(normalizedState);
          const isQueuedForRetry = Boolean(
            hasIdentifier && retryingDownloadId != null && normalizedId === retryingDownloadId
          );
          const isRetrying = Boolean(isQueuedForRetry && isRetryPending);
          const shouldDisableButton =
            !canRetry || isRetrying || isQueuedForRetry || (isRetryPending && (!retryingDownloadId || !hasIdentifier));
          const queuedLabel = formatTimestamp(download.queuedAt);
          const startedLabel = formatTimestamp(download.startedAt);
          const completedLabel = formatTimestamp(download.completedAt);
          const createdLabel = formatTimestamp(download.createdAt);
          const updatedLabel = formatTimestamp(download.updatedAt);

          return (
            <TableRow key={rowKey}>
              <TableCell>
                <div className="space-y-1">
                  <span className="text-sm font-medium text-foreground">
                    {download.filename ?? download.id ?? 'Unbekannter Download'}
                  </span>
                  {download.id ? (
                    <span className="text-xs text-muted-foreground">ID: {download.id}</span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <div className="space-y-1">
                  <StatusBadge status={download.state} label={formatStateLabel(download.state)} />
                  {download.lastError ? (
                    <span className="block text-xs text-rose-600 dark:text-rose-300">
                      Fehler: {download.lastError}
                    </span>
                  ) : null}
                  {download.nextRetryAt ? (
                    <span className="block text-xs text-muted-foreground">
                      Nächster Retry: {formatTimestamp(download.nextRetryAt) ?? 'Unbekannt'}
                    </span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="w-48">
                {progressValue !== null ? (
                  <div className="space-y-1">
                    <Progress value={progressValue} aria-label={`Fortschritt ${progressValue}%`} />
                    <span className="block text-xs text-muted-foreground">{progressValue}%</span>
                  </div>
                ) : (
                  <span className="text-sm text-muted-foreground">Keine Angaben</span>
                )}
              </TableCell>
              <TableCell>
                <div className="space-y-1">
                  <span className="text-sm text-foreground">{download.username ?? '–'}</span>
                  {queuedLabel ? (
                    <span className="block text-xs text-muted-foreground">Wartet seit: {queuedLabel}</span>
                  ) : null}
                  {!queuedLabel && startedLabel ? (
                    <span className="block text-xs text-muted-foreground">Gestartet: {startedLabel}</span>
                  ) : null}
                  {completedLabel ? (
                    <span className="block text-xs text-muted-foreground">Abgeschlossen: {completedLabel}</span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <div className="space-y-1">
                  <span className="text-sm text-foreground">Priorität: {formatPriority(download.priority)}</span>
                  <span className="block text-xs text-muted-foreground">{formatRetryCount(download.retryCount)}</span>
                </div>
              </TableCell>
              <TableCell>
                <div className="space-y-1 text-xs text-muted-foreground">
                  {createdLabel ? <span>Erstellt: {createdLabel}</span> : null}
                  {updatedLabel ? <span>Aktualisiert: {updatedLabel}</span> : null}
                </div>
              </TableCell>
              <TableCell>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={shouldDisableButton}
                  onClick={() => onRetryDownload?.(download)}
                >
                  {isRetrying ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      Wird erneut gestartet …
                    </span>
                  ) : (
                    'Retry'
                  )}
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
};

export default SoulseekDownloadList;
