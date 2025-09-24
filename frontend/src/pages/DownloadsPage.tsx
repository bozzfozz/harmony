import { FormEvent, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Progress } from '../components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { useToast } from '../hooks/useToast';
import { fetchActiveDownloads, startDownload, DownloadEntry } from '../lib/api';
import { useMutation, useQuery } from '../lib/query';
import { mapProgressToPercent } from '../lib/utils';

const DownloadsPage = () => {
  const { toast } = useToast();
  const [trackId, setTrackId] = useState('');
  const [showAllDownloads, setShowAllDownloads] = useState(false);

  const {
    data: downloads,
    isLoading,
    isError,
    refetch
  } = useQuery<DownloadEntry[]>({
    queryKey: ['downloads', showAllDownloads ? 'all' : 'active'],
    queryFn: () => fetchActiveDownloads(showAllDownloads),
    refetchInterval: 15000,
    onError: () =>
      toast({
        title: 'Downloads konnten nicht geladen werden',
        description: 'Bitte Backend-Logs prüfen.',
        variant: 'destructive'
      })
  });

  const startDownloadMutation = useMutation({
    mutationFn: startDownload,
    onSuccess: (entry) => {
      toast({
        title: 'Download gestartet',
        description: entry?.filename
          ? `"${entry.filename}" wurde zur Warteschlange hinzugefügt.`
          : 'Download wurde gestartet.'
      });
      setTrackId('');
      void refetch();
    },
    onError: () => {
      toast({
        title: 'Download fehlgeschlagen',
        description: 'Bitte Eingabe prüfen und erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!trackId.trim()) {
      toast({
        title: 'Track-ID erforderlich',
        description: 'Bitte Track oder Dateiname eingeben.',
        variant: 'destructive'
      });
      return;
    }
    void startDownloadMutation.mutate({ track_id: trackId.trim() });
  };

  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(undefined, {
    dateStyle: 'short',
    timeStyle: 'short'
  }), []);

  const rows = useMemo(() => downloads ?? [], [downloads]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Download-Management</CardTitle>
          <CardDescription>
            Verwalten Sie aktive Downloads und fügen Sie neue Dateien zur Warteschlange hinzu.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={handleSubmit}>
            <Input
              value={trackId}
              onChange={(event) => setTrackId(event.target.value)}
              placeholder="Track oder Dateiname eingeben"
              aria-label="Track-ID"
            />
            <Button type="submit" disabled={startDownloadMutation.isPending}>
              {startDownloadMutation.isPending ? (
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Wird gestartet...
                </span>
              ) : (
                'Download starten'
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="space-y-2 sm:flex sm:items-center sm:justify-between sm:space-y-0">
          <div>
            <CardTitle>Aktive Downloads</CardTitle>
            <CardDescription>
              {showAllDownloads
                ? 'Alle vom Backend gemeldeten Transfers inklusive abgeschlossener und fehlgeschlagener Einträge.'
                : 'Übersicht der aktuell aktiven Transfers.'}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAllDownloads((value) => !value)}
            aria-pressed={showAllDownloads}
          >
            {showAllDownloads ? 'Nur aktive' : 'Alle anzeigen'}
          </Button>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-6 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" aria-label="Lade Downloads" />
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive">Downloads konnten nicht geladen werden.</p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">Keine Downloads aktiv.</p>
          ) : (
            <div className="overflow-hidden rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Dateiname</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Fortschritt</TableHead>
                    <TableHead>Angelegt</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((download) => {
                    const progressValue = mapProgressToPercent(download.progress);
                    const createdAtLabel = download.created_at
                      ? dateFormatter.format(new Date(download.created_at))
                      : 'Unbekannt';
                    return (
                      <TableRow key={download.id}>
                        <TableCell className="text-sm text-muted-foreground">{download.id}</TableCell>
                        <TableCell className="text-sm font-medium">{download.filename}</TableCell>
                        <TableCell className="capitalize">{download.status}</TableCell>
                        <TableCell className="w-64">
                          <div className="space-y-2">
                            <Progress value={progressValue} aria-label={`Fortschritt ${progressValue}%`} />
                            <span className="text-xs text-muted-foreground">{progressValue}%</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{createdAtLabel}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default DownloadsPage;
