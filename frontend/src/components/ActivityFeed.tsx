import { useEffect, useMemo, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { useToast } from '../hooks/useToast';
import { fetchActivityFeed, ActivityItem } from '../lib/api';
import { useQuery } from '../lib/query';

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

  const rows = useMemo(() => data ?? [], [data]);

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
                    <TableCell className="text-sm font-medium capitalize">{item.type}</TableCell>
                    <TableCell>
                      <span className="inline-flex items-center rounded-full bg-muted px-2 py-1 text-xs font-semibold uppercase text-muted-foreground">
                        {item.status}
                      </span>
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
