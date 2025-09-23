import { Loader2 } from 'lucide-react';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle
} from '../components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '../components/ui/table';
import { Progress } from '../components/ui/progress';
import { useToast } from '../hooks/useToast';
import { useQuery } from '../lib/query';
import {
  fetchJobs,
  fetchMatchingStats,
  fetchServices,
  fetchSoulseekOverview,
  fetchSpotifyOverview,
  fetchSystemOverview
} from '../lib/api';

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

const statusStyles: Record<string, string> = {
  running: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200',
  success: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200',
  pending: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200',
  error: 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200',
  stopped: 'bg-slate-200 text-slate-700 dark:bg-slate-900 dark:text-slate-200',
  paused: 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-200'
};

const Dashboard = () => {
  const { toast } = useToast();

  const systemOverviewQuery = useQuery({
    queryKey: ['system-overview'],
    queryFn: fetchSystemOverview,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: 'Failed to load system overview',
        description: 'Please check the backend connection.',
        variant: 'destructive'
      })
  });

  const servicesQuery = useQuery({
    queryKey: ['services'],
    queryFn: fetchServices,
    refetchInterval: 30000
  });

  const jobsQuery = useQuery({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
    refetchInterval: 45000
  });

  const spotifyQuery = useQuery({
    queryKey: ['spotify-overview'],
    queryFn: fetchSpotifyOverview,
    refetchInterval: 60000
  });

  const soulseekQuery = useQuery({
    queryKey: ['soulseek-overview'],
    queryFn: fetchSoulseekOverview,
    refetchInterval: 60000
  });

  const matchingStatsQuery = useQuery({
    queryKey: ['matching-stats'],
    queryFn: fetchMatchingStats,
    refetchInterval: 60000
  });

  const isLoading =
    systemOverviewQuery.isLoading &&
    servicesQuery.isLoading &&
    jobsQuery.isLoading &&
    spotifyQuery.isLoading &&
    soulseekQuery.isLoading;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const systemOverview = systemOverviewQuery.data ?? {
    cpuUsage: 0,
    memoryUsage: 0,
    storageUsage: 0,
    runningServices: 0
  };
  const services = servicesQuery.data ?? [];
  const jobs = jobsQuery.data ?? [];
  const spotify = spotifyQuery.data ?? {
    playlists: 0,
    artists: 0,
    tracks: 0,
    lastSync: ''
  };
  const soulseek = soulseekQuery.data ?? {
    downloads: 0,
    uploads: 0,
    queue: 0,
    lastSync: ''
  };
  const matchingStats = matchingStatsQuery.data ?? {
    pending: 0,
    processed: 0,
    conflicts: 0,
    lastRun: ''
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>CPU usage</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{systemOverview.cpuUsage}%</div>
            <Progress value={systemOverview.cpuUsage} className="mt-3" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Memory usage</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{systemOverview.memoryUsage}%</div>
            <Progress value={systemOverview.memoryUsage} className="mt-3" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Storage usage</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{systemOverview.storageUsage}%</div>
            <Progress value={systemOverview.storageUsage} className="mt-3" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Running services</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{systemOverview.runningServices}</div>
            <p className="mt-1 text-sm text-muted-foreground">Services online</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Spotify overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span>Playlists</span>
              <span className="font-medium">{spotify.playlists}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span>Artists</span>
              <span className="font-medium">{spotify.artists}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span>Tracks</span>
              <span className="font-medium">{spotify.tracks}</span>
            </div>
            <p className="text-xs text-muted-foreground">Last sync: {formatDateTime(spotify.lastSync)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Soulseek overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span>Downloads</span>
              <span className="font-medium">{soulseek.downloads}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span>Uploads</span>
              <span className="font-medium">{soulseek.uploads}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span>Queue size</span>
              <span className="font-medium">{soulseek.queue}</span>
            </div>
            <p className="text-xs text-muted-foreground">Last sync: {formatDateTime(soulseek.lastSync)}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Matching jobs</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <div>
            <p className="text-sm text-muted-foreground">Pending</p>
            <p className="text-lg font-semibold">{matchingStats.pending}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Processed</p>
            <p className="text-lg font-semibold">{matchingStats.processed}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Conflicts</p>
            <p className="text-lg font-semibold">{matchingStats.conflicts}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Last run</p>
            <p className="text-lg font-semibold">{formatDateTime(matchingStats.lastRun)}</p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Services</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Uptime</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {services.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                      No services reported yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  services.map((service) => (
                    <TableRow key={service.name}>
                      <TableCell className="font-medium">{service.name}</TableCell>
                      <TableCell>
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                            statusStyles[service.status] ?? 'bg-slate-200 text-slate-700'
                          }`}
                        >
                          {service.status}
                        </span>
                      </TableCell>
                      <TableCell>{service.uptime}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Background jobs</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Job</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                      No jobs have run yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  jobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell className="font-medium">{job.name}</TableCell>
                      <TableCell>
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                            statusStyles[job.status] ?? 'bg-slate-200 text-slate-700'
                          }`}
                        >
                          {job.status}
                        </span>
                      </TableCell>
                      <TableCell>{formatDateTime(job.updatedAt)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Dashboard;
