import { useMemo } from 'react';
import { Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Progress } from './ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { useToast } from '../hooks/useToast';
import { fetchActiveDownloads, DownloadEntry } from '../lib/api';
import { useQuery } from '../lib/query';
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

const DownloadWidget = () => {
  const { toast } = useToast();
  const navigate = useNavigate();

  const { data, isLoading, isError } = useQuery<DownloadEntry[]>({
    queryKey: ['downloads', 'active-widget'],
    queryFn: () => fetchActiveDownloads(),
    refetchInterval: 15000,
    onError: () =>
      toast({
        title: 'Downloads konnten nicht geladen werden',
        description: 'Bitte versuchen Sie es später erneut.',
        variant: 'destructive'
      })
  });

  const entries = useMemo(() => (data ?? []).slice(0, 5), [data]);
  const hasMore = (data?.length ?? 0) > 5;

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
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((download) => {
                  const progressValue = mapProgressToPercent(download.progress);
                  return (
                    <TableRow key={download.id}>
                      <TableCell className="text-sm font-medium">{download.filename}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatStatus(download.status)}
                      </TableCell>
                      <TableCell className="w-48">
                        <div className="space-y-1">
                          <Progress value={progressValue} aria-label={`Fortschritt ${progressValue}%`} />
                          <span className="text-xs text-muted-foreground">{progressValue}%</span>
                        </div>
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
