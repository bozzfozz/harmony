import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { useToast } from '../../hooks/useToast';
import { ApiError } from '../../api/client';
import {
  LIBRARY_POLL_INTERVAL_MS,
  cancelDownload,
  exportDownloads,
  getDownloads,
  startDownload,
  updateDownloadPriority,
  useRetryDownload
} from '../../api/services/downloads';
import type { DownloadEntry } from '../../api/types';
import { useMutation, useQuery } from '../../lib/query';
import { mapProgressToPercent } from '../../lib/utils';

const statusOptions = [
  { value: 'all', label: 'Alle Status' },
  { value: 'running', label: 'Laufend' },
  { value: 'queued', label: 'Warteschlange' },
  { value: 'completed', label: 'Abgeschlossen' },
  { value: 'failed', label: 'Fehlgeschlagen' },
  { value: 'cancelled', label: 'Abgebrochen' }
];

const DOWNLOAD_SOURCE = 'library_manual';

const extractDownloadDetails = (value: string): { username?: string; filename?: string } | null => {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  const protocolMatch = /^soulseek:\/\/([^/]+)\/(.+)$/i.exec(trimmed);
  if (protocolMatch) {
    return {
      username: protocolMatch[1].trim(),
      filename: protocolMatch[2].trim()
    };
  }

  const separator = '::';
  const separatorIndex = trimmed.indexOf(separator);
  if (separatorIndex > 0) {
    const potentialUsername = trimmed.slice(0, separatorIndex).trim();
    const potentialFilename = trimmed.slice(separatorIndex + separator.length).trim();
    if (potentialUsername && potentialFilename) {
      return {
        username: potentialUsername,
        filename: potentialFilename
      };
    }
  }

  return null;
};

interface LibraryDownloadsProps {
  isActive?: boolean;
}

const LibraryDownloads = ({ isActive = true }: LibraryDownloadsProps = {}) => {
  const { toast } = useToast();
  const [username, setUsername] = useState('');
  const [downloadInput, setDownloadInput] = useState('');
  const [showAllDownloads, setShowAllDownloads] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [priorityDrafts, setPriorityDrafts] = useState<Record<number, number>>({});
  const [exportingFormat, setExportingFormat] = useState<'csv' | 'json' | null>(null);

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
    onSuccess: (entry, payload) => {
      const submittedFile = payload?.files?.[0];
      const displayName = entry?.filename || submittedFile?.filename || submittedFile?.name || '';
      toast({
        title: 'Download gestartet',
        description: displayName
          ? `"${displayName}" wurde zur Warteschlange hinzugefügt.`
          : 'Download wurde gestartet.'
      });
      setDownloadInput('');
      setUsername((current) => current || payload.username);
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

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedInput = downloadInput.trim();
    if (!trimmedInput) {
      toast({
        title: 'Track-Information erforderlich',
        description: 'Bitte Track oder Dateiname eingeben.',
        variant: 'destructive'
      });
      return;
    }

    const derived = extractDownloadDetails(trimmedInput);
    let normalizedUsername = username.trim();

    if (!normalizedUsername && derived?.username) {
      normalizedUsername = derived.username;
      setUsername(derived.username);
    }

    if (!normalizedUsername) {
      toast({
        title: 'Benutzername erforderlich',
        description: 'Bitte Soulseek-Benutzernamen angeben oder im Trackfeld hinterlegen.',
        variant: 'destructive'
      });
      return;
    }

    const resolvedFilename = derived?.filename?.trim() || trimmedInput;

    void startDownloadMutation.mutate({
      username: normalizedUsername,
      files: [
        {
          filename: resolvedFilename,
          name: trimmedInput,
          source: DOWNLOAD_SOURCE
        }
      ]
    });
  };

  const handleStatusChange = (nextStatus: string) => {
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
          <form
            className="grid gap-3 sm:grid-cols-[repeat(3,minmax(0,1fr))] sm:items-end"
            onSubmit={handleSubmit}
          >
            <label className="flex flex-col gap-2 text-sm font-medium">
              Soulseek-Benutzername
              <Input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="Soulseek-Benutzername"
                aria-label="Soulseek-Benutzername"
              />
            </label>
            <div className="flex flex-col gap-1 sm:col-span-2">
              <label className="flex flex-col gap-2 text-sm font-medium">
                Datei oder Track
                <Input
                  value={downloadInput}
                  onChange={(event) => setDownloadInput(event.target.value)}
                  placeholder="Dateiname, Track oder soulseek://-Link"
                  aria-label="Datei oder Track"
                />
              </label>
              <p className="text-xs text-muted-foreground">
                Optional: Format „soulseek://nutzer/pfad“ oder „nutzer::datei“ zur automatischen Zuordnung.
              </p>
            </div>
            <div className="sm:col-start-3 sm:self-end">
              <Button type="submit" disabled={startDownloadMutation.isPending} className="w-full sm:w-auto">
                {startDownloadMutation.isPending ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Wird gestartet...
                  </span>
                ) : (
                  'Download starten'
                )}
              </Button>
            </div>
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
              <Select value={statusFilter} onValueChange={handleStatusChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Alle Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {statusOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
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
      </Card>
    </div>
  );
};

export default LibraryDownloads;
