import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import {
  fetchJobs,
  fetchMatchingStats,
  fetchServices,
  fetchSoulseekOverview,
  fetchSpotifyOverview,
  fetchSystemOverview,
  ServiceStatus
} from '../lib/api';
import { useToast } from '../hooks/useToast';
import { cn } from '../lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';

const statusColorMap: Record<ServiceStatus['status'], string> = {
  online: 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-300',
  offline: 'bg-rose-500/20 text-rose-600 dark:text-rose-300',
  syncing: 'bg-amber-500/20 text-amber-600 dark:text-amber-300',
  idle: 'bg-sky-500/20 text-sky-600 dark:text-sky-300'
};

const Dashboard = () => {
  const { toast } = useToast();

  const systemQuery = useQuery({
    queryKey: ['system-overview'],
    queryFn: fetchSystemOverview,
    refetchInterval: 30000,
    onError: () => toast({ title: 'System overview unavailable', variant: 'destructive' })
  });

  const servicesQuery = useQuery({
    queryKey: ['services-status'],
    queryFn: fetchServices,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load services', variant: 'destructive' })
  });

  const jobsQuery = useQuery({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load jobs', variant: 'destructive' })
  });

  const spotifyQuery = useQuery({
    queryKey: ['spotify-overview'],
    queryFn: fetchSpotifyOverview,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Spotify overview unavailable', variant: 'destructive' })
  });

  const soulseekQuery = useQuery({
    queryKey: ['soulseek-overview'],
    queryFn: fetchSoulseekOverview,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Soulseek overview unavailable', variant: 'destructive' })
  });

  const matchingQuery = useQuery({
    queryKey: ['matching-overview'],
    queryFn: fetchMatchingStats,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Matching overview unavailable', variant: 'destructive' })
  });

  const loading = useMemo(
    () =>
      systemQuery.isLoading ||
      servicesQuery.isLoading ||
      jobsQuery.isLoading ||
      spotifyQuery.isLoading ||
      soulseekQuery.isLoading ||
      matchingQuery.isLoading,
    [
      systemQuery.isLoading,
      servicesQuery.isLoading,
      jobsQuery.isLoading,
      spotifyQuery.isLoading,
      soulseekQuery.isLoading,
      matchingQuery.isLoading
    ]
  );

  return (
    <div className="space-y-6">
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : null}
      <div className="card-grid">
        <Card>
          <CardHeader>
            <CardTitle>System Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex justify-between"><span>Hostname</span><span>{systemQuery.data?.hostname}</span></div>
            <div className="flex justify-between"><span>Uptime</span><span>{systemQuery.data?.uptime}</span></div>
            <div className="flex justify-between"><span>CPU Load</span><span>{systemQuery.data?.cpuLoad ?? 0}%</span></div>
            <div className="flex justify-between"><span>Memory Usage</span><span>{systemQuery.data?.memoryUsage ?? 0}%</span></div>
            <div className="flex justify-between"><span>Disk Usage</span><span>{systemQuery.data?.diskUsage ?? 0}%</span></div>
            <div className="flex justify-between"><span>Version</span><span>{systemQuery.data?.version}</span></div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Spotify</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex justify-between"><span>Playlists</span><span>{spotifyQuery.data?.playlists ?? 0}</span></div>
            <div className="flex justify-between"><span>Artists</span><span>{spotifyQuery.data?.artists ?? 0}</span></div>
            <div className="flex justify-between"><span>Tracks</span><span>{spotifyQuery.data?.tracks ?? 0}</span></div>
            <div className="flex justify-between"><span>Last Sync</span><span>{spotifyQuery.data?.lastSync}</span></div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Soulseek</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex justify-between"><span>Downloads</span><span>{soulseekQuery.data?.downloads ?? 0}</span></div>
            <div className="flex justify-between"><span>Uploads</span><span>{soulseekQuery.data?.uploads ?? 0}</span></div>
            <div className="flex justify-between"><span>Queue</span><span>{soulseekQuery.data?.queue ?? 0}</span></div>
            <div className="flex justify-between"><span>Last Sync</span><span>{soulseekQuery.data?.lastSync}</span></div>
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Service Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2">
              {servicesQuery.data?.map((service) => (
                <div
                  key={service.name}
                  className="flex items-center justify-between rounded-lg border bg-background p-4"
                >
                  <div>
                    <p className="text-sm font-semibold">{service.name}</p>
                    <p className="text-xs text-muted-foreground">Last sync {service.lastSync ?? '–'}</p>
                  </div>
                  <span className={cn('rounded-full px-3 py-1 text-xs font-medium', statusColorMap[service.status])}>
                    {service.status}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Matching</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex justify-between"><span>Pending</span><span>{matchingQuery.data?.pending ?? 0}</span></div>
            <div className="flex justify-between"><span>Processed</span><span>{matchingQuery.data?.processed ?? 0}</span></div>
            <div className="flex justify-between"><span>Conflicts</span><span>{matchingQuery.data?.conflicts ?? 0}</span></div>
            <div className="flex justify-between"><span>Last run</span><span>{matchingQuery.data?.lastRun}</span></div>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Active Jobs</CardTitle>
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

export default Dashboard;
