import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '../lib/query';
import { Loader2 } from 'lucide-react';
import {
  fetchRootStatus,
  fetchSettings,
  fetchSpotifyStatus,
  fetchPlexStatus,
  fetchSoulseekStatus,
  fetchSoulseekDownloads,
  fetchSpotifyPlaylists,
  SoulseekDownloadEntry
} from '../lib/api';
import { useToast } from '../hooks/useToast';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';

const SERVICE_STATUS_LABELS: Record<string, string> = {
  connected: 'Verbunden',
  unauthenticated: 'Authentifizierung erforderlich',
  disconnected: 'Getrennt'
};

const formatDateTime = (value: string | undefined) => {
  if (!value) {
    return '–';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
};

const formatDuration = (seconds: number) => {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  const parts = [hours, minutes, secs].map((part) => part.toString().padStart(2, '0'));
  return parts.join(':');
};

const deriveWorkerStatus = (statuses: Array<string | undefined>) => {
  if (statuses.every((status) => status === 'connected')) {
    return 'Aktiv';
  }
  if (statuses.some((status) => status === 'connected')) {
    return 'Degradiert';
  }
  return 'Offline';
};

const Dashboard = () => {
  const { toast } = useToast();
  const [uptimeSeconds, setUptimeSeconds] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const update = () => {
      setUptimeSeconds(Math.floor((Date.now() - startedAt) / 1000));
    };
    update();
    const interval = window.setInterval(update, 1000);
    return () => window.clearInterval(interval);
  }, []);

  const rootQuery = useQuery({
    queryKey: ['root-status'],
    queryFn: fetchRootStatus,
    refetchInterval: 30000,
    onError: () => toast({
      title: '❌ Fehler beim Laden',
      description: 'API-Status konnte nicht abgerufen werden.',
      variant: 'destructive'
    })
  });

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () => toast({
      title: '❌ Fehler beim Laden',
      description: 'Einstellungen konnten nicht geladen werden.',
      variant: 'destructive'
    })
  });

  const spotifyStatusQuery = useQuery({
    queryKey: ['spotify-status'],
    queryFn: fetchSpotifyStatus,
    refetchInterval: 30000,
    onError: () => toast({
      title: '❌ Fehler beim Laden',
      description: 'Spotify-Status konnte nicht geladen werden.',
      variant: 'destructive'
    })
  });

  const plexStatusQuery = useQuery({
    queryKey: ['plex-status'],
    queryFn: fetchPlexStatus,
    refetchInterval: 30000,
    onError: () => toast({
      title: '❌ Fehler beim Laden',
      description: 'Plex-Status konnte nicht geladen werden.',
      variant: 'destructive'
    })
  });

  const soulseekStatusQuery = useQuery({
    queryKey: ['soulseek-status'],
    queryFn: fetchSoulseekStatus,
    refetchInterval: 30000,
    onError: () => toast({
      title: '❌ Fehler beim Laden',
      description: 'Soulseek-Status konnte nicht geladen werden.',
      variant: 'destructive'
    })
  });

  const downloadsQuery = useQuery({
    queryKey: ['soulseek-downloads'],
    queryFn: fetchSoulseekDownloads,
    refetchInterval: 30000,
    onError: () => toast({
      title: '❌ Fehler beim Laden',
      description: 'Download-Liste konnte nicht geladen werden.',
      variant: 'destructive'
    })
  });

  const playlistsQuery = useQuery({
    queryKey: ['spotify-playlists'],
    queryFn: fetchSpotifyPlaylists,
    refetchInterval: 30000,
    onError: () => toast({
      title: '❌ Fehler beim Laden',
      description: 'Spotify-Playlists konnten nicht geladen werden.',
      variant: 'destructive'
    })
  });

  const isLoading =
    rootQuery.isLoading ||
    settingsQuery.isLoading ||
    spotifyStatusQuery.isLoading ||
    plexStatusQuery.isLoading ||
    soulseekStatusQuery.isLoading ||
    downloadsQuery.isLoading ||
    playlistsQuery.isLoading;

  const serviceStatuses = useMemo(
    () => [
      {
        name: 'Spotify',
        status: spotifyStatusQuery.data?.status ?? 'disconnected'
      },
      {
        name: 'Plex',
        status: plexStatusQuery.data?.status ?? 'disconnected'
      },
      {
        name: 'Soulseek',
        status: soulseekStatusQuery.data?.status ?? 'disconnected'
      },
      {
        name: 'Beets',
        status: settingsQuery.data?.settings?.BEETS_ENABLED ? 'connected' : 'disconnected'
      }
    ],
    [
      spotifyStatusQuery.data?.status,
      plexStatusQuery.data?.status,
      soulseekStatusQuery.data?.status,
      settingsQuery.data?.settings?.BEETS_ENABLED
    ]
  );

  const totalPlaylistTracks = useMemo(
    () =>
      playlistsQuery.data?.playlists.reduce((sum, playlist) => sum + (playlist.track_count ?? 0), 0) ?? 0,
    [playlistsQuery.data?.playlists]
  );

  const downloads: SoulseekDownloadEntry[] = downloadsQuery.data?.downloads ?? [];
  const queuedDownloads = downloads.filter((download) => download.state === 'queued');
  const activeDownloads = downloads.filter((download) => download.state === 'downloading' || download.state === 'running');

  const workerStatus = deriveWorkerStatus(serviceStatuses.map((service) => service.status));

  return (
    <div className="space-y-6">
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>System Information</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Backend Version</p>
              <p className="text-lg font-semibold">{rootQuery.data?.version ?? '–'}</p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">API Status</p>
              <p className="text-lg font-semibold">{rootQuery.data?.status ?? 'unbekannt'}</p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Datenbank</p>
              <p className="text-lg font-semibold">
                {settingsQuery.isSuccess ? 'Verbunden' : 'Fehler'}
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Worker Status</p>
              <p className="text-lg font-semibold">{workerStatus}</p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Letzte Aktualisierung</p>
              <p className="text-lg font-semibold">
                {formatDateTime(settingsQuery.data?.updated_at)}
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Uptime</p>
              <p className="text-lg font-semibold">{formatDuration(uptimeSeconds)}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Spotify Überblick</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex justify-between">
              <span>Playlists</span>
              <span>{playlistsQuery.data?.playlists.length ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span>Tracks gesamt</span>
              <span>{totalPlaylistTracks}</span>
            </div>
            <div className="flex justify-between">
              <span>Zuletzt aktualisiert</span>
              <span>
                {formatDateTime(playlistsQuery.data?.playlists[0]?.updated_at)}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Services</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {serviceStatuses.map((service) => (
              <div key={service.name} className="flex items-center justify-between rounded-lg border bg-background p-4">
                <div>
                  <p className="text-sm font-semibold">{service.name}</p>
                  <p className="text-xs text-muted-foreground">
                    Status wird alle 30 Sekunden aktualisiert
                  </p>
                </div>
                <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                  {SERVICE_STATUS_LABELS[service.status] ?? service.status}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Soulseek Übersicht</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex justify-between">
              <span>Downloads aktiv</span>
              <span>{activeDownloads.length}</span>
            </div>
            <div className="flex justify-between">
              <span>Downloads in Warteschlange</span>
              <span>{queuedDownloads.length}</span>
            </div>
            <div className="flex justify-between">
              <span>Gesamt</span>
              <span>{downloads.length}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Aktive Downloads</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Datei</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Fortschritt</TableHead>
                <TableHead className="text-right">Aktualisiert</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {downloads.map((download) => (
                <TableRow key={download.id}>
                  <TableCell className="font-medium">{download.filename}</TableCell>
                  <TableCell>{download.state}</TableCell>
                  <TableCell className="min-w-[160px]">
                    <Progress value={Math.min(100, Math.max(0, download.progress))} />
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">
                    {formatDateTime(download.updated_at)}
                  </TableCell>
                </TableRow>
              ))}
              {downloads.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                    Keine aktiven Downloads vorhanden.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

export default Dashboard;
