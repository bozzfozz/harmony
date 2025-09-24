import { useCallback, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Button } from '../components/ui/button';
import Select from '../components/ui/select';
import { ActivityHistoryResponse, fetchActivityHistory } from '../lib/api';
import { useQuery } from '../lib/query';
import { useToast } from '../hooks/useToast';

const PAGE_SIZE = 20;

const typeOptions = [
  { value: 'all', label: 'Alle Typen' },
  { value: 'sync', label: 'Sync' },
  { value: 'download', label: 'Download' },
  { value: 'search', label: 'Suche' },
  { value: 'metadata', label: 'Metadaten' },
  { value: 'worker', label: 'Worker' }
] as const;

const statusOptions = [
  { value: 'all', label: 'Alle Stati' },
  { value: 'ok', label: 'OK' },
  { value: 'failed', label: 'Fehlgeschlagen' },
  { value: 'partial', label: 'Teilweise' }
] as const;

const ActivityHistoryPage = () => {
  const { toast } = useToast();
  const [offset, setOffset] = useState(0);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  const queryFn = useCallback(
    () => fetchActivityHistory(PAGE_SIZE, offset, typeFilter ?? undefined, statusFilter ?? undefined),
    [offset, statusFilter, typeFilter]
  );

  const { data, isLoading, isError } = useQuery<ActivityHistoryResponse>({
    queryKey: ['activity-history', PAGE_SIZE, offset, typeFilter ?? 'all', statusFilter ?? 'all'],
    queryFn,
    onError: () =>
      toast({
        title: 'Activity History nicht erreichbar',
        description: 'Bitte Backend-Logs prüfen.',
        variant: 'destructive'
      })
  });

  const items = data?.items ?? [];
  const totalCount = data?.total_count ?? 0;

  const canGoBack = offset > 0;
  const canGoForward = offset + PAGE_SIZE < totalCount;

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = totalCount === 0 ? 1 : Math.ceil(totalCount / PAGE_SIZE);

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(undefined, {
        dateStyle: 'short',
        timeStyle: 'medium'
      }),
    []
  );

  const handleNext = () => {
    if (canGoForward) {
      setOffset((value) => value + PAGE_SIZE);
    }
  };

  const handlePrev = () => {
    if (canGoBack) {
      setOffset((value) => Math.max(0, value - PAGE_SIZE));
    }
  };

  const handleTypeChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    setOffset(0);
    setTypeFilter(value === 'all' ? null : value);
  };

  const handleStatusChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    setOffset(0);
    setStatusFilter(value === 'all' ? null : value);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Activity History</CardTitle>
          <CardDescription>
            Persistente Ereignisliste mit Paging und Filtern. Insgesamt {totalCount} Einträge gespeichert.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="flex flex-col gap-2 text-sm font-medium">
              Typ
              <Select value={typeFilter ?? 'all'} onChange={handleTypeChange} aria-label="Activity-Typ filtern">
                {typeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-2 text-sm font-medium">
              Status
              <Select value={statusFilter ?? 'all'} onChange={handleStatusChange} aria-label="Activity-Status filtern">
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <div className="overflow-hidden rounded-lg border">
            {isLoading ? (
              <div className="flex items-center justify-center py-10 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" aria-label="Lade Activity History" />
              </div>
            ) : isError ? (
              <div className="py-10 text-center text-sm text-destructive">
                Die Activity History konnte nicht geladen werden.
              </div>
            ) : items.length === 0 ? (
              <div className="py-10 text-center text-sm text-muted-foreground">Keine Events gefunden.</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Typ</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Details</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((entry) => (
                    <TableRow key={`${entry.timestamp}-${entry.type}-${entry.status}`}>
                      <TableCell>{dateFormatter.format(new Date(entry.timestamp))}</TableCell>
                      <TableCell className="font-medium">{entry.type}</TableCell>
                      <TableCell>
                        <span className="inline-flex rounded-full bg-muted px-2 py-1 text-xs font-semibold uppercase tracking-wide">
                          {entry.status}
                        </span>
                      </TableCell>
                      <TableCell>
                        {entry.details ? (
                          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs text-muted-foreground">
                            {JSON.stringify(entry.details, null, 2)}
                          </pre>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>

          <div className="flex flex-col items-center justify-between gap-3 border-t pt-4 text-sm text-muted-foreground sm:flex-row">
            <div>
              Seite {currentPage} von {totalPages}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handlePrev} disabled={!canGoBack}>
                Zurück
              </Button>
              <Button variant="outline" size="sm" onClick={handleNext} disabled={!canGoForward}>
                Weiter
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default ActivityHistoryPage;
