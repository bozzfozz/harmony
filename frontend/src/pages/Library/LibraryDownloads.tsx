import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import FailedBadge from '../../components/downloads/FailedBadge';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input
} from '../../components/ui/shadcn';
import { Progress } from '../../components/ui/progress';
import { Select } from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { useToast } from '../../hooks/useToast';
import {
  ApiError,
  DownloadEntry,
  DOWNLOAD_STATS_QUERY_KEY,
  LIBRARY_POLL_INTERVAL_MS,
  cancelDownload,
  exportDownloads,
  getDownloads,
  startDownload,
  updateDownloadPriority,
  useClearDownload,
  useRetryAllFailed,
  useRetryDownload
} from '../../lib/api';
import { useMutation, useQuery, useQueryClient } from '../../lib/query';
import { mapProgressToPercent } from '../../lib/utils';

const statusOptions = [
  { value: 'all', label: 'Alle Status' },
  { value: 'running', label: 'Laufend' },
  { value: 'queued', label: 'Warteschlange' },
  { value: 'completed', label: 'Abgeschlossen' },
  { value: 'failed', label: 'Fehlgeschlagen' },
  { value: 'cancelled', label: 'Abgebrochen' },
  { value: 'blocked', label: 'Blockiert' }
];

interface LibraryDownloadsProps {
  isActive?: boolean;
}

const LibraryDownloads = ({ isActive = true }: LibraryDownloadsProps = {}) => {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [trackId, setTrackId] = useState('');
  const [showAllDownloads, setShowAllDownloads] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [priorityDrafts, setPriorityDrafts] = useState<Record<number, number>>({});
  const [exportingFormat, setExportingFormat] = useState<'csv' | 'json' | null>(null);
  const [failedCount, setFailedCount] = useState(0);

  const isActiveRef = useRef(isActive);

  useEffect(() => {
    isActiveRef.current = isActive;
  }, [isActive]);

  const showErrorToast = (message: Parameters<typeof toast>[0]) => {
    if (!isActiveRef.current) {
      return;
    }
    toast(message);
  };

  const handleCredentialsError = (error: unknown) => {
    if (error instanceof ApiError && error.status === 503) {
      if (!error.handled) {
        showErrorToast({
          title: '❌ Zugangsdaten erforderlich',
          description: 'Bitte hinterlegen Sie gültige Zugangsdaten in den Einstellungen.',
          variant: 'destructive'
        });
      }
      error.markHandled();
      return true;
    }
    return false;
  };

  const {
    data: downloads,
    isLoading,
    isError,
    refetch
  } = useQuery<DownloadEntry[]>({
    queryKey: ['downloads', showAllDownloads ? 'all' : 'active', statusFilter],
    queryFn: () =>
      getDownloads({
        includeAll: showAllDownloads,
        status: statusFilter === 'all' ? undefined : statusFilter
      }),
    refetchInterval: isActive ? LIBRARY_POLL_INTERVAL_MS : false,
    onError: (error) => {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      showErrorToast({
        title: 'Downloads konnten nicht geladen werden',
        description: 'Bitte Backend-Logs prüfen.',
        variant: 'destructive'
      });
    },
    enabled: isActive
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
    onError: (error) => {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      showErrorToast({
        title: 'Download fehlgeschlagen',
        description: 'Bitte Eingabe prüfen und erneut versuchen.',
        variant: 'destructive'
      });
    }
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
    onError: (error) => {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      showErrorToast({
        title: 'Abbruch fehlgeschlagen',
        description: 'Bitte erneut versuchen oder Backend-Logs prüfen.',
        variant: 'destructive'
      });
    }
  });

  const retryDownloadMutation = useRetryDownload({
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
      queryClient.invalidateQueries({ queryKey: [...DOWNLOAD_STATS_QUERY_KEY] });
    },
    onError: (error) => {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      showErrorToast({
        title: 'Neu-Start fehlgeschlagen',
        description: 'Bitte erneut versuchen oder Backend-Logs prüfen.',
        variant: 'destructive'
      });
    }
  });

  const clearDownloadMutation = useClearDownload({
    onSuccess: ({ filename }) => {
      toast({
        title: 'Download entfernt',
        description: filename ? `"${filename}" wurde aus der Liste entfernt.` : undefined
      });
      void refetch();
      queryClient.invalidateQueries({ queryKey: [...DOWNLOAD_STATS_QUERY_KEY] });
    },
    onError: (error) => {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      showErrorToast({
        title: 'Eintrag konnte nicht entfernt werden',
        description: 'Bitte erneut versuchen oder Backend-Logs prüfen.',
        variant: 'destructive'
      });
    }
  });

  const updatePriorityMutation = useMutation({
    mutationFn: ({ id, priority }: { id: string; priority: number }) =>
      updateDownloadPriority(id, priority),
    onSuccess: (entry) => {
      setPriorityDrafts((drafts) => {
        const next = { ...drafts };
        delete next[Number(entry.id)];
        return next;
      });
      toast({
        title: 'Priorität aktualisiert',
        description: `Neue Priorität: ${entry.priority}`
      });
      void refetch();
    },
    onError: (error) => {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      showErrorToast({
        title: 'Priorität konnte nicht aktualisiert werden',
        description: 'Bitte erneut versuchen oder Backend-Logs prüfen.',
        variant: 'destructive'
      });
    }
  });

  const retryAllFailedMutation = useRetryAllFailed({
    onSuccess: (result) => {
      const { requeued, skipped } = result;
      const parts = [`Neu gestartet: ${requeued}`];
      parts.push(`Übersprungen: ${skipped}`);
      toast({
        title: 'Fehlgeschlagene Downloads neu gestartet',
        description: parts.join(' • ')
      });
      void refetch();
    },
    onError: (error) => {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.status === 404 || error.status === 405 || error.status === 501) {
          toast({
            title: 'Aktion nicht verfügbar',
            description: 'Das Backend unterstützt kein globales Neu-Starten.',
            variant: 'default'
          });
          return;
        }
        if (error.handled) {
          return;
        }
        error.markHandled();
        showErrorToast({
          title: 'Neu-Start fehlgeschlagen',
          description: error.message,
          variant: 'destructive'
        });
        return;
      }
      const description = error instanceof Error ? error.message : 'Unbekannter Fehler';
      showErrorToast({
        title: 'Neu-Start fehlgeschlagen',
        description,
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

  const handleStatusChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const nextStatus = event.target.value;
    setStatusFilter(nextStatus);
    if (nextStatus === 'failed') {
      setShowAllDownloads(true);
    }
  };

  const handlePriorityInputChange = (downloadId: number, value: number) => {
    setPriorityDrafts((drafts) => ({ ...drafts, [downloadId]: value }));
  };

  const handlePrioritySubmit = (download: DownloadEntry) => {
    const numericId = Number(download.id);
    const draftValue = priorityDrafts[numericId];
    const nextPriority = Number.isFinite(draftValue)
      ? Math.round(draftValue)
      : download.priority ?? 0;

    if (nextPriority === (download.priority ?? 0)) {
      return;
    }

    if (updatePriorityMutation.isPending) {
      return;
    }

    updatePriorityMutation.mutate({ id: String(download.id), priority: nextPriority });
  };

  const handleExport = async (format: 'csv' | 'json') => {
    try {
      setExportingFormat(format);
      const blob = await exportDownloads(format, {
        status: statusFilter === 'all' ? undefined : statusFilter
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const dateFragment = new Date().toISOString().slice(0, 10);
      link.href = url;
      link.download = `downloads_${dateFragment}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast({ title: `Export ${format.toUpperCase()} erstellt` });
    } catch (error) {
      if (handleCredentialsError(error)) {
        return;
      }
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      showErrorToast({
        title: 'Export fehlgeschlagen',
        description: 'Bitte erneut versuchen oder Backend-Logs prüfen.',
        variant: 'destructive'
      });
    } finally {
      setExportingFormat(null);
    }
  };

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(undefined, {
        dateStyle: 'short',
        timeStyle: 'short'
      }),
    []
  );

  const filteredRows = useMemo(() => {
    const list = downloads ?? [];
    const query = searchTerm.trim().toLowerCase();
    if (!query) {
      return list;
    }
    return list.filter((download) => {
      const filename = download.filename?.toLowerCase() ?? '';
      const username = download.username?.toLowerCase() ?? '';
      return filename.includes(query) || username.includes(query);
    });
  }, [downloads, searchTerm]);

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
        <CardHeader className="space-y-4">
          <div className="space-y-2 sm:flex sm:items-center sm:justify-between sm:space-y-0">
            <div>
              <CardTitle>Aktive Downloads</CardTitle>
              <CardDescription>
                {showAllDownloads
                  ? 'Alle vom Backend gemeldeten Transfers inklusive abgeschlossener und fehlgeschlagener Einträge.'
                  : 'Übersicht der aktuell aktiven Transfers.'}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <FailedBadge
                isActive={isActive}
                isSelected={statusFilter === 'failed'}
                onSelect={() =>
                  setStatusFilter((current) => {
                    if (current === 'failed') {
                      return 'all';
                    }
                    setShowAllDownloads(true);
                    return 'failed';
                  })
                }
                onCountChange={setFailedCount}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowAllDownloads((value) => !value)}
                aria-pressed={showAllDownloads}
              >
                {showAllDownloads ? 'Nur aktive' : 'Alle anzeigen'}
              </Button>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-2 text-sm font-medium">
              Status
              <Select value={statusFilter} onChange={handleStatusChange} aria-label="Status filtern">
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-2 text-sm font-medium sm:col-span-2">
              Suche
              <Input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Nach Dateiname oder Benutzer filtern"
                aria-label="Downloads durchsuchen"
              />
            </label>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {retryAllFailedMutation.isSupported ? (
              <Button
                size="sm"
                onClick={() => {
                  if (failedCount === 0 || retryAllFailedMutation.isPending) {
                    return;
                  }
                  const message =
                    failedCount === 1
                      ? 'Soll der fehlgeschlagene Download erneut gestartet werden?'
                      : `Sollen ${failedCount} fehlgeschlagene Downloads erneut gestartet werden?`;
                  const confirmed = window.confirm(message);
                  if (!confirmed) {
                    return;
                  }
                  void retryAllFailedMutation.mutate();
                }}
                disabled={failedCount === 0 || retryAllFailedMutation.isPending}
              >
                {retryAllFailedMutation.isPending ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Wird neu gestartet...
                  </span>
                ) : (
                  'Alle fehlgeschlagenen erneut versuchen'
                )}
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleExport('json')}
              disabled={exportingFormat === 'json'}
            >
              {exportingFormat === 'json' ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              Export JSON
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleExport('csv')}
              disabled={exportingFormat === 'csv'}
            >
              {exportingFormat === 'csv' ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              Export CSV
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-6 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" aria-label="Lade Downloads" />
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive">Downloads konnten nicht geladen werden.</p>
          ) : filteredRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">Keine Downloads gefunden.</p>
          ) : (
            <div className="overflow-hidden rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Dateiname</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Priorität</TableHead>
                    <TableHead>Fortschritt</TableHead>
                    <TableHead>Angelegt</TableHead>
                    <TableHead>Aktionen</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredRows.map((download) => {
                    const numericId = Number(download.id);
                    const progressValue = mapProgressToPercent(download.progress);
                    const createdAtLabel = download.created_at
                      ? dateFormatter.format(new Date(download.created_at))
                      : 'Unbekannt';
                    const statusLower = (download.status ?? '').toLowerCase();
                    const showCancel = statusLower === 'running' || statusLower === 'queued' || statusLower === 'downloading';
                    const showRetry = statusLower === 'failed' || statusLower === 'cancelled';
                    const showClear = statusLower === 'failed';
                    const draftPriority = priorityDrafts[numericId];
                    const priorityValue = Number.isFinite(draftPriority)
                      ? draftPriority
                      : download.priority ?? 0;

                    return (
                      <TableRow key={download.id}>
                        <TableCell className="text-sm text-muted-foreground">{download.id}</TableCell>
                        <TableCell className="text-sm font-medium">
                          <div className="space-y-1">
                            <span>{download.filename}</span>
                            {download.username ? (
                              <span className="block text-xs text-muted-foreground">{download.username}</span>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell className="capitalize">{download.status.replace(/[_-]+/g, ' ')}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Input
                              type="number"
                              className="w-20"
                              value={priorityValue}
                              onChange={(event) =>
                                handlePriorityInputChange(numericId, Number(event.target.value))
                              }
                              aria-label={`Priorität für ${download.filename}`}
                            />
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => handlePrioritySubmit(download)}
                              disabled={updatePriorityMutation.isPending}
                            >
                              Setzen
                            </Button>
                          </div>
                        </TableCell>
                        <TableCell className="w-64">
                          <div className="space-y-2">
                            <Progress value={progressValue} aria-label={`Fortschritt ${progressValue}%`} />
                            <span className="text-xs text-muted-foreground">{progressValue}%</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{createdAtLabel}</TableCell>
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
                              disabled={
                                cancelDownloadMutation.isPending ||
                                retryDownloadMutation.isPending ||
                                clearDownloadMutation.isPending
                              }
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
                              disabled={
                                cancelDownloadMutation.isPending ||
                                retryDownloadMutation.isPending ||
                                clearDownloadMutation.isPending
                              }
                            >
                              Neu starten
                            </Button>
                          ) : null}
                          {showClear ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:bg-destructive/10"
                              onClick={() =>
                                clearDownloadMutation.mutate({
                                  id: String(download.id),
                                  filename: download.filename
                                })
                              }
                              disabled={
                                clearDownloadMutation.isPending ||
                                cancelDownloadMutation.isPending ||
                                retryDownloadMutation.isPending
                              }
                            >
                              Entfernen
                            </Button>
                          ) : null}
                          {!showCancel && !showRetry && !showClear ? (
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
      </Card>
    </div>
  );
};

export default LibraryDownloads;
