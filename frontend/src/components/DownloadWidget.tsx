import { useMemo } from 'react';
import { Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Progress } from './ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { useToast } from '../hooks/useToast';
import { cancelDownload, fetchDownloads, retryDownload, DownloadEntry } from '../lib/api';
import { useMutation, useQuery } from '../lib/query';
import { mapProgressToPercent } from '../lib/utils';

const formatStatus = (status: string | undefined) => {
  if (!status) {
    return 'Unbekannt';
  }
  return status
    .toString()
    .replace(/[_-]+/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
};

const DISPLAY_LIMIT = 5;

const DownloadWidget = () => {
  const { toast } = useToast();
  const navigate = useNavigate();

  const { data, isLoading, isError, refetch } = useQuery<DownloadEntry[]>({
    queryKey: ['downloads', 'active-widget'],
    queryFn: () => fetchDownloads({ limit: DISPLAY_LIMIT }),
    refetchInterval: 15000,
    onError: () =>
      toast({
        title: 'Downloads konnten nicht geladen werden',
        description: 'Bitte versuchen Sie es später erneut.',
        variant: 'destructive'
      })
  });

  const cancelDownloadMutation = useMutation({
    mutationFn: async ({ id }: { id: string; filename: string }) => cancelDownload(id),
    onSuccess: (_, { filename }) => {
      toast({
        title: 'Download abgebrochen',
        description: filename ? `"${filename}" wurde gestoppt.` : 'Download wurde abgebrochen.'
      });
      void refetch();
    },
    onError: () => {
      toast({
        title: 'Abbruch fehlgeschlagen',
        description: 'Bitte erneut versuchen oder Backend-Logs prüfen.',
        variant: 'destructive'
      });
    }
  });

  const retryDownloadMutation = useMutation({
    mutationFn: async ({ id }: { id: string; filename: string }) => retryDownload(id),
    onSuccess: (entry, { filename }) => {
      toast({
        title: 'Download neu gestartet',
        description: entry?.filename
          ? `"${entry.filename}" wurde erneut zur Warteschlange hinzugefügt.`
          : filename
            ? `"${filename}" wurde erneut gestartet.`
            : 'Download wurde erneut gestartet.'
      });
      void refetch();
    },
    onError: () => {
      toast({
        title: 'Neu-Start fehlgeschlagen',
        description: 'Bitte erneut versuchen oder Backend-Logs prüfen.',
        variant: 'destructive'
      });
    }
  });

  const entries = useMemo(() => {
    const downloads = data ?? [];
    return downloads
      .filter((download) => {
        const status = (download.status ?? '').toLowerCase();
        return status === 'running' || status === 'queued' || status === 'downloading';
      })
      .slice(0, DISPLAY_LIMIT);
  }, [data]);
  const hasMore = (data?.length ?? 0) > DISPLAY_LIMIT;

  const handleNavigate = () => {
    navigate('/downloads');
  };

  return (
    <Card>
      <CardHeader className="space-y-1 pb-2">
        <CardTitle className="text-base">Aktive Downloads</CardTitle>
        <p className="text-sm text-muted-foreground">
          Übersicht der zuletzt gestarteten Transfers.
        </p>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" aria-label="Lade Downloads" />
          </div>
        ) : isError ? (
          <p className="text-sm text-destructive">Downloads konnten nicht geladen werden.</p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">Keine aktiven Downloads.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Dateiname</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Fortschritt</TableHead>
                  <TableHead>Aktionen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((download) => {
                  const progressValue = mapProgressToPercent(download.progress);
                  const statusLower = (download.status ?? '').toLowerCase();
                  const showCancel =
                    statusLower === 'running' ||
                    statusLower === 'queued' ||
                    statusLower === 'downloading';
                  const showRetry = statusLower === 'failed' || statusLower === 'cancelled';
                  return (
                    <TableRow key={download.id}>
                      <TableCell className="text-sm font-medium">{download.filename}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        <div className="space-y-1">
                          <span>{formatStatus(download.status)}</span>
                          <span className="block text-xs text-muted-foreground">
                            Priorität: {download.priority ?? 0}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="w-48">
                        <div className="space-y-1">
                          <Progress value={progressValue} aria-label={`Fortschritt ${progressValue}%`} />
                          <span className="text-xs text-muted-foreground">{progressValue}%</span>
                        </div>
                      </TableCell>
                      <TableCell className="space-x-2 whitespace-nowrap">
                        {showCancel ? (
                          <Button
                            type="button"
                            variant="destructive"
                            size="sm"
                            onClick={() =>
                              cancelDownloadMutation.mutate({
                                id: String(download.id),
                                filename: download.filename
                              })
                            }
                            disabled={cancelDownloadMutation.isPending || retryDownloadMutation.isPending}
                          >
                            Abbrechen
                          </Button>
                        ) : null}
                        {showRetry ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              retryDownloadMutation.mutate({
                                id: String(download.id),
                                filename: download.filename
                              })
                            }
                            disabled={cancelDownloadMutation.isPending || retryDownloadMutation.isPending}
                          >
                            Neu starten
                          </Button>
                        ) : null}
                        {!showCancel && !showRetry ? (
                          <span className="text-xs text-muted-foreground">Keine Aktion</span>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
      {hasMore ? (
        <div className="flex justify-end border-t px-6 py-3">
          <Button type="button" variant="outline" size="sm" onClick={handleNavigate}>
            Alle anzeigen
          </Button>
        </div>
      ) : null}
    </Card>
  );
};

export default DownloadWidget;
