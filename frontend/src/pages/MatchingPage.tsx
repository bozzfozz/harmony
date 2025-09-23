import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '../components/ui/table';
import { useQuery } from '../lib/query';
import { fetchMatchingHistory, fetchMatchingStats } from '../lib/api';

const formatDateTime = (value: string) => {
  if (!value) {
    return 'Never';
  }
  try {
    return new Intl.DateTimeFormat('en', {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date(value));
  } catch (error) {
    return value;
  }
};

const MatchingPage = () => {
  const statsQuery = useQuery({
    queryKey: ['matching-stats'],
    queryFn: fetchMatchingStats,
    refetchInterval: 45000
  });

  const historyQuery = useQuery({
    queryKey: ['matching-history'],
    queryFn: fetchMatchingHistory,
    refetchInterval: 60000
  });

  if (statsQuery.isLoading || historyQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const stats = statsQuery.data ?? {
    pending: 0,
    processed: 0,
    conflicts: 0,
    lastRun: ''
  };
  const history = historyQuery.data ?? [];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Matching status</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-sm text-muted-foreground">Pending</p>
            <p className="text-2xl font-semibold">{stats.pending}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Processed</p>
            <p className="text-2xl font-semibold">{stats.processed}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Conflicts</p>
            <p className="text-2xl font-semibold">{stats.conflicts}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Last run</p>
            <p className="text-2xl font-semibold">{formatDateTime(stats.lastRun)}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Matched</TableHead>
                <TableHead>Unmatched</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                    No matching runs have been recorded yet.
                  </TableCell>
                </TableRow>
              ) : (
                history.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell>{formatDateTime(entry.createdAt)}</TableCell>
                    <TableCell className="font-medium">{entry.source}</TableCell>
                    <TableCell>{entry.matched}</TableCell>
                    <TableCell>{entry.unmatched}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

export default MatchingPage;
