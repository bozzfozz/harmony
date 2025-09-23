import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { fetchJobs, fetchMatchingStats } from '../lib/api';
import { useToast } from '../hooks/useToast';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';

const MatchingPage = () => {
  const { toast } = useToast();

  const statsQuery = useQuery({
    queryKey: ['matching-overview'],
    queryFn: fetchMatchingStats,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load matching stats', variant: 'destructive' })
  });

  const jobsQuery = useQuery({
    queryKey: ['matching-jobs'],
    queryFn: fetchJobs,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load matching jobs', variant: 'destructive' })
  });

  const loading = statsQuery.isLoading || jobsQuery.isLoading;

  return (
    <div className="space-y-6">
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>Matching Statistics</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 text-sm text-muted-foreground">
          <div className="flex justify-between rounded-lg border bg-background p-4">
            <span>Pending</span>
            <span className="font-semibold text-foreground">{statsQuery.data?.pending ?? 0}</span>
          </div>
          <div className="flex justify-between rounded-lg border bg-background p-4">
            <span>Processed</span>
            <span className="font-semibold text-foreground">{statsQuery.data?.processed ?? 0}</span>
          </div>
          <div className="flex justify-between rounded-lg border bg-background p-4">
            <span>Conflicts</span>
            <span className="font-semibold text-foreground">{statsQuery.data?.conflicts ?? 0}</span>
          </div>
          <div className="flex justify-between rounded-lg border bg-background p-4">
            <span>Last Run</span>
            <span className="font-semibold text-foreground">{statsQuery.data?.lastRun ?? '–'}</span>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Matching Jobs</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead className="text-right">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobsQuery.data?.map((job) => (
                <TableRow key={job.id}>
                  <TableCell className="font-medium">{job.name}</TableCell>
                  <TableCell>{job.status}</TableCell>
                  <TableCell className="min-w-[160px]">
                    <Progress value={job.progress} />
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">{job.updatedAt}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

export default MatchingPage;
