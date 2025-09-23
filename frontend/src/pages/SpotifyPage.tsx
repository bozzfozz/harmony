import { FormEvent, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '../components/ui/table';
import { useToast } from '../hooks/useToast';
import { useQuery } from '../lib/query';
import {
  fetchSpotifyPlaylists,
  fetchSpotifyStatus,
  searchSpotifyTracks,
  SpotifyPlaylist,
  SpotifyTrackSummary
} from '../lib/api';
import useServiceSettingsForm from '../hooks/useServiceSettingsForm';

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

const settingsFields = [
  { key: 'SPOTIFY_CLIENT_ID', label: 'Client ID', placeholder: 'Client ID' },
  { key: 'SPOTIFY_CLIENT_SECRET', label: 'Client secret', placeholder: 'Client secret' },
  {
    key: 'SPOTIFY_REDIRECT_URI',
    label: 'Redirect URI',
    placeholder: 'https://example.com/callback'
  }
] as const;

const SpotifyPage = () => {
  const { toast } = useToast();
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState<SpotifyTrackSummary[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const statusQuery = useQuery({
    queryKey: ['spotify-status'],
    queryFn: fetchSpotifyStatus,
    refetchInterval: 45000,
    onError: () =>
      toast({
        title: 'Failed to load Spotify status',
        description: 'Check the backend connection and credentials.',
        variant: 'destructive'
      })
  });

  const playlistsQuery = useQuery({
    queryKey: ['spotify-playlists'],
    queryFn: fetchSpotifyPlaylists,
    refetchInterval: 60000,
    onError: () =>
      toast({
        title: 'Failed to load playlists',
        description: 'Spotify playlists could not be fetched.',
        variant: 'destructive'
      })
  });

  const { form, onSubmit, handleReset, isSaving, isLoading } = useServiceSettingsForm({
    fields: settingsFields,
    loadErrorDescription: 'Spotify settings could not be loaded.',
    successTitle: 'Spotify settings saved',
    errorTitle: 'Failed to save Spotify settings'
  });

  const playlists = playlistsQuery.data ?? [];

  const status = useMemo(
    () => ({
      status: statusQuery.data?.status ?? 'unknown',
      artist_count: statusQuery.data?.artist_count ?? null,
      album_count: statusQuery.data?.album_count ?? null,
      track_count: statusQuery.data?.track_count ?? null,
      last_scan: statusQuery.data?.last_scan ?? null
    }),
    [statusQuery.data]
  );

  const handleSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = searchTerm.trim();
    if (!trimmed) {
      toast({
        title: 'Enter a search term',
        description: 'Please provide a query before searching Spotify.',
        variant: 'destructive'
      });
      return;
    }
    try {
      setIsSearching(true);
      const tracks = await searchSpotifyTracks(trimmed);
      setSearchResults(tracks);
      if (tracks.length === 0) {
        toast({ title: 'No results found', description: `No tracks matched "${trimmed}".` });
      }
    } catch (error) {
      console.error('Spotify search failed', error);
      toast({
        title: 'Spotify search failed',
        description: 'The backend did not return any results.',
        variant: 'destructive'
      });
    } finally {
      setIsSearching(false);
    }
  };

  const renderPlaylistRows = (items: SpotifyPlaylist[]) => {
    if (items.length === 0) {
      return (
        <TableRow>
          <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
            No playlists have been synced yet.
          </TableCell>
        </TableRow>
      );
    }
    return items.map((playlist) => (
      <TableRow key={playlist.id}>
        <TableCell className="font-medium">{playlist.name}</TableCell>
        <TableCell>{playlist.track_count}</TableCell>
        <TableCell>{formatDateTime(playlist.updated_at)}</TableCell>
      </TableRow>
    ));
  };

  const renderSearchRows = (tracks: SpotifyTrackSummary[]) => {
    if (tracks.length === 0) {
      return (
        <TableRow>
          <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
            No tracks have been loaded yet.
          </TableCell>
        </TableRow>
      );
    }
    return tracks.map((track) => {
      const artists = (track.artists ?? []).map((artist) => artist.name).filter(Boolean);
      return (
        <TableRow key={track.id ?? `${track.name}-${artists.join('-')}`}>
          <TableCell className="font-medium">{track.name ?? 'Unknown track'}</TableCell>
          <TableCell>{artists.length > 0 ? artists.join(', ') : 'Unknown artist'}</TableCell>
          <TableCell>{track.album?.name ?? 'Unknown album'}</TableCell>
          <TableCell>
            {track.duration_ms ? `${Math.round(track.duration_ms / 1000)}s` : '—'}
          </TableCell>
        </TableRow>
      );
    });
  };

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="search">Search</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Connection status</CardTitle>
            </CardHeader>
            <CardContent>
              {statusQuery.isLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <div className="space-y-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span>Status</span>
                    <span className="font-medium capitalize">{status.status}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Artists</span>
                    <span className="font-medium">{status.artist_count ?? '—'}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Albums</span>
                    <span className="font-medium">{status.album_count ?? '—'}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Tracks</span>
                    <span className="font-medium">{status.track_count ?? '—'}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Last scan: {status.last_scan ? formatDateTime(status.last_scan) : 'Never'}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Playlists</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              {playlistsQuery.isLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Tracks</TableHead>
                      <TableHead>Updated</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>{renderPlaylistRows(playlists)}</TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </TabsContent>
      <TabsContent value="search">
        <Card>
          <CardHeader>
            <CardTitle>Track search</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <form onSubmit={handleSearch} className="flex flex-col gap-2 sm:flex-row">
              <Input
                placeholder="Search for a track"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
              />
              <Button type="submit" disabled={isSearching}>
                {isSearching ? 'Searching…' : 'Search'}
              </Button>
            </form>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Track</TableHead>
                    <TableHead>Artists</TableHead>
                    <TableHead>Album</TableHead>
                    <TableHead>Duration</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>{renderSearchRows(searchResults)}</TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="settings">
        <Card>
          <CardHeader>
            <CardTitle>Spotify credentials</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <form onSubmit={onSubmit} className="space-y-6">
                <div className="grid gap-4">
                  {settingsFields.map(({ key, label, placeholder }) => (
                    <div key={key} className="space-y-2">
                      <Label htmlFor={key}>{label}</Label>
                      <Input id={key} placeholder={placeholder} {...form.register(key)} />
                    </div>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <Button type="submit" disabled={isSaving}>
                    {isSaving ? 'Saving…' : 'Save changes'}
                  </Button>
                  <Button type="button" variant="outline" onClick={handleReset} disabled={isSaving}>
                    Reset
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
};

export default SpotifyPage;
