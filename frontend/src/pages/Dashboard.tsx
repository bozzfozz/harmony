import { useMemo } from 'react';
import { Loader2 } from 'lucide-react';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle
} from '../components/ui/card';
import ActivityFeed from '../components/ActivityFeed';
import DownloadWidget from '../components/DownloadWidget';
import { useToast } from '../hooks/useToast';
import { useQuery } from '../lib/query';
import {
  fetchBeetsStats,
  fetchPlexLibraries,
  fetchPlexStatus,
  fetchSoulseekDownloads,
  fetchSoulseekStatus,
  fetchSpotifyPlaylists,
  fetchSpotifyStatus
} from '../lib/api';

const Dashboard = () => {
  const { toast } = useToast();

  const spotifyStatusQuery = useQuery({
    queryKey: ['spotify-status'],
    queryFn: fetchSpotifyStatus,
    refetchInterval: 45000,
    onError: () =>
      toast({
        title: 'Failed to load Spotify status',
        description: 'Check the Spotify credentials.',
        variant: 'destructive'
      })
  });

  const spotifyPlaylistsQuery = useQuery({
    queryKey: ['spotify-dashboard-playlists'],
    queryFn: fetchSpotifyPlaylists,
    refetchInterval: 60000
  });

  const plexStatusQuery = useQuery({
    queryKey: ['plex-status'],
    queryFn: fetchPlexStatus,
    refetchInterval: 45000,
    onError: () =>
      toast({
        title: 'Failed to load Plex status',
        description: 'The Plex server may be offline.',
        variant: 'destructive'
      })
  });

  const plexLibrariesQuery = useQuery({
    queryKey: ['plex-dashboard-libraries'],
    queryFn: fetchPlexLibraries,
    refetchInterval: 120000
  });

  const soulseekStatusQuery = useQuery({
    queryKey: ['soulseek-status'],
    queryFn: fetchSoulseekStatus,
    refetchInterval: 45000,
    onError: () =>
      toast({
        title: 'Failed to load Soulseek status',
        description: 'The Soulseek daemon did not respond.',
        variant: 'destructive'
      })
  });

  const soulseekDownloadsQuery = useQuery({
    queryKey: ['soulseek-dashboard-downloads'],
    queryFn: fetchSoulseekDownloads,
    refetchInterval: 30000
  });

  const beetsStatsQuery = useQuery({
    queryKey: ['beets-stats'],
    queryFn: fetchBeetsStats,
    refetchInterval: 60000,
    onError: () =>
      toast({
        title: 'Failed to load Beets statistics',
        description: 'The Beets integration may be unreachable.',
        variant: 'destructive'
      })
  });

  const isLoading =
    spotifyStatusQuery.isLoading &&
    plexStatusQuery.isLoading &&
    soulseekStatusQuery.isLoading &&
    beetsStatsQuery.isLoading;

  const spotifyPlaylistsCount = spotifyPlaylistsQuery.data?.length ?? 0;
  const plexSessionCount = useMemo(() => {
    const sessions = plexStatusQuery.data?.sessions;
    if (Array.isArray(sessions)) {
      return sessions.length;
    }
    if (sessions && typeof sessions === 'object') {
      return Object.keys(sessions).length;
    }
    return 0;
  }, [plexStatusQuery.data?.sessions]);

  const plexLibraryCount = useMemo(() => {
    const raw = plexLibrariesQuery.data as Record<string, unknown> | undefined;
    if (!raw) {
      return 0;
    }
    const container = (raw.MediaContainer ?? raw) as Record<string, unknown>;
    const directories = container.Directory ?? container.directories;
    if (Array.isArray(directories)) {
      return directories.length;
    }
    if (directories) {
      return 1;
    }
    return 0;
  }, [plexLibrariesQuery.data]);

  const soulseekDownloads = soulseekDownloadsQuery.data ?? [];
  const beetsStats = beetsStatsQuery.data?.stats ?? {};

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>Spotify</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span>Status</span>
              <span className="font-medium capitalize">
                {spotifyStatusQuery.data?.status ?? 'unknown'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>Playlists</span>
              <span className="font-medium">{spotifyPlaylistsCount}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Tracks synced</span>
              <span className="font-medium">{spotifyStatusQuery.data?.track_count ?? '—'}</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Plex</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span>Status</span>
              <span className="font-medium capitalize">
                {plexStatusQuery.data?.status ?? 'unknown'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>Sessions</span>
              <span className="font-medium">{plexSessionCount}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Libraries</span>
              <span className="font-medium">{plexLibraryCount}</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Soulseek</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span>Status</span>
              <span className="font-medium capitalize">
                {soulseekStatusQuery.data?.status ?? 'unknown'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>Queued downloads</span>
              <span className="font-medium">{soulseekDownloads.length}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Active items</span>
              <span className="font-medium">
                {
                  soulseekDownloads.filter((download) => download.state !== 'finished').length
                }
              </span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Beets</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {Object.keys(beetsStats).length === 0 ? (
              <p className="text-muted-foreground">No statistics available yet.</p>
            ) : (
              Object.entries(beetsStats)
                .slice(0, 3)
                .map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between">
                    <span className="capitalize">{key.replace(/_/g, ' ')}</span>
                    <span className="font-medium">{value}</span>
                  </div>
                ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <ActivityFeed />
        <DownloadWidget />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Matching</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            Matching results are generated on demand. Use the matching page to test Spotify to Plex
            or Spotify to Soulseek matching scenarios.
          </p>
          <p className="text-muted-foreground">
            Each successful match is stored by the backend and can be reviewed through your
            database tooling.
          </p>
        </CardContent>
      </Card>
    </div>
  );
};

export default Dashboard;
