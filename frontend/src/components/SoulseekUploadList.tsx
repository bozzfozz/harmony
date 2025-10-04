import StatusBadge from './StatusBadge';
import { Progress } from './ui/progress';
import { Button } from './ui/shadcn';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import type { NormalizedSoulseekUpload } from '../api/services/soulseek';
import { mapProgressToPercent } from '../lib/utils';

const formatSize = (value: number | null): string => {
  if (value === null || Number.isNaN(value)) {
    return '–';
  }
  const thresholds = [
    { limit: 1024 ** 3, suffix: 'GB' },
    { limit: 1024 ** 2, suffix: 'MB' },
    { limit: 1024, suffix: 'KB' }
  ];
  for (const { limit, suffix } of thresholds) {
    if (value >= limit) {
      return `${(value / limit).toFixed(1)} ${suffix}`;
    }
  }
  if (value >= 0) {
    return `${Math.round(value)} B`;
  }
  return '–';
};

const formatSpeed = (value: number | null): string => {
  if (value === null || Number.isNaN(value)) {
    return '–';
  }
  if (value >= 1024 ** 2) {
    return `${(value / 1024 ** 2).toFixed(1)} MB/s`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB/s`;
  }
  if (value >= 0) {
    return `${Math.round(value)} B/s`;
  }
  return '–';
};

const formatStateLabel = (state: string): string => {
  const normalized = state.toLowerCase();
  const labels: Record<string, string> = {
    uploading: 'Wird hochgeladen',
    queued: 'Wartend',
    completed: 'Abgeschlossen',
    failed: 'Fehlgeschlagen',
    cancelled: 'Abgebrochen',
    paused: 'Pausiert'
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

export interface SoulseekUploadListProps {
  uploads?: NormalizedSoulseekUpload[];
  isLoading: boolean;
  isError: boolean;
  onRetry?: () => void;
}

const SoulseekUploadList = ({ uploads, isLoading, isError, onRetry }: SoulseekUploadListProps) => {
  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Uploads werden geladen …</p>;
  }

  if (isError) {
    return (
      <div className="flex items-center justify-between gap-4 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-900/20 dark:text-rose-200">
        <span>Uploads konnten nicht geladen werden.</span>
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Erneut versuchen
          </Button>
        ) : null}
      </div>
    );
  }

  if (!uploads || uploads.length === 0) {
    return <p className="text-sm text-muted-foreground">Aktuell sind keine Uploads aktiv.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Datei</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Fortschritt</TableHead>
          <TableHead>Benutzer</TableHead>
          <TableHead>Größe</TableHead>
          <TableHead>Geschwindigkeit</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {uploads.map((upload, index) => {
          const progressValue =
            upload.progress === null || Number.isNaN(upload.progress)
              ? null
              : mapProgressToPercent(upload.progress);
          const rowKey = upload.id ?? `${upload.filename ?? 'upload'}-${index}`;
          return (
            <TableRow key={rowKey}>
              <TableCell>
                <div className="space-y-1">
                  <span className="text-sm font-medium text-foreground">
                    {upload.filename ?? upload.id ?? 'Unbenanntes Upload'}
                  </span>
                  {upload.id ? (
                    <span className="text-xs text-muted-foreground">ID: {upload.id}</span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <div className="space-y-1">
                  <StatusBadge status={upload.state} label={formatStateLabel(upload.state)} />
                  {formatTimestamp(upload.startedAt) ? (
                    <span className="block text-xs text-muted-foreground">
                      Gestartet: {formatTimestamp(upload.startedAt)}
                    </span>
                  ) : formatTimestamp(upload.queuedAt) ? (
                    <span className="block text-xs text-muted-foreground">
                      Warteschlange seit: {formatTimestamp(upload.queuedAt)}
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
                <span className="text-sm text-foreground">{upload.username ?? '–'}</span>
              </TableCell>
              <TableCell>
                <span className="text-sm text-foreground">{formatSize(upload.size)}</span>
              </TableCell>
              <TableCell>
                <span className="text-sm text-foreground">{formatSpeed(upload.speed)}</span>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
};

export default SoulseekUploadList;
