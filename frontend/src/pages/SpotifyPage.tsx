import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '../lib/query';
import { Loader2, Search } from 'lucide-react';
import {
  fetchSettings,
  fetchSpotifyPlaylists,
  searchSpotifyTracks,
  updateSetting,
  SpotifyPlaylist
} from '../lib/api';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { useToast } from '../hooks/useToast';

const SPOTIFY_FIELDS = [
  { key: 'SPOTIFY_CLIENT_ID', label: 'Client ID' },
  { key: 'SPOTIFY_CLIENT_SECRET', label: 'Client Secret' },
  { key: 'SPOTIFY_REDIRECT_URI', label: 'Redirect URI' }
] as const;

type SpotifySettingsForm = Record<(typeof SPOTIFY_FIELDS)[number]['key'], string>;

const SpotifyPage = () => {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [hasSearched, setHasSearched] = useState(false);

  const playlistsQuery = useQuery({
    queryKey: ['spotify-playlists'],
    queryFn: fetchSpotifyPlaylists,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Spotify-Playlists konnten nicht geladen werden.',
        variant: 'destructive'
      })
  });

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Einstellungen konnten nicht geladen werden.',
        variant: 'destructive'
      })
  });

  const searchMutation = useMutation({
    mutationFn: (term: string) => searchSpotifyTracks(term),
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Die Spotify-Suche ist fehlgeschlagen.',
        variant: 'destructive'
      })
  });

  const defaultValues = useMemo(() => {
    const settings = settingsQuery.data?.settings ?? {};
    return SPOTIFY_FIELDS.reduce<SpotifySettingsForm>((acc, field) => {
      acc[field.key] = settings[field.key] ?? '';
      return acc;
    }, {} as SpotifySettingsForm);
  }, [settingsQuery.data?.settings]);

  const form = useForm<SpotifySettingsForm>({ defaultValues });

  useEffect(() => {
    form.reset(defaultValues);
  }, [defaultValues, form]);

  const mutation = useMutation({
    mutationFn: async (values: SpotifySettingsForm) => {
      const settings = settingsQuery.data?.settings ?? {};
      const updates = Object.entries(values).filter(([key, value]) => (settings[key] ?? '') !== value);
      await Promise.all(
        updates.map(([key, value]) => updateSetting({ key, value: value.trim() === '' ? null : value }))
      );
    },
    onSuccess: () => {
      toast({ title: '✅ Einstellungen gespeichert' });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: () => toast({ title: '❌ Fehler beim Speichern', variant: 'destructive' })
  });

  const handleSubmit = (values: SpotifySettingsForm) => {
    mutation.mutate(values);
  };

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = searchTerm.trim();
    if (!trimmed) {
      return;
    }
    setHasSearched(true);
    searchMutation.mutate(trimmed);
  };

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Übersicht</TabsTrigger>
        <TabsTrigger value="settings">Einstellungen</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="space-y-6">
        {playlistsQuery.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : null}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Spotify Playlists</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Tracks</TableHead>
                    <TableHead className="text-right">Aktualisiert</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(playlistsQuery.data?.playlists ?? []).map((playlist: SpotifyPlaylist) => (
                    <TableRow key={playlist.id}>
                      <TableCell className="font-medium">{playlist.name}</TableCell>
                      <TableCell>{playlist.track_count}</TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {new Date(playlist.updated_at).toLocaleString()}
                      </TableCell>
                    </TableRow>
                  ))}
                  {(playlistsQuery.data?.playlists ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                        Keine Playlists vorhanden.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Track-Suche</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <form className="flex items-center gap-2" onSubmit={handleSearch}>
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Track oder Artist suchen"
                    className="pl-9"
                  />
                </div>
                <Button type="submit" disabled={searchMutation.isPending}>
                  {searchMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Suchen
                </Button>
              </form>
              <div className="space-y-2">
                {hasSearched && searchMutation.data?.items?.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Keine Treffer gefunden.</p>
                ) : null}
                <ul className="space-y-2">
                  {(searchMutation.data?.items ?? []).map((item, index) => {
                    const name = (item as Record<string, unknown>).name ?? 'Unbekannter Titel';
                    const artists = Array.isArray((item as Record<string, unknown>).artists)
                      ? ((item as Record<string, unknown>).artists as Array<Record<string, unknown>>)
                          .map((artist) => artist?.name)
                          .filter(Boolean)
                          .join(', ')
                      : undefined;
                    const album = (item as Record<string, unknown>).album as Record<string, unknown> | undefined;
                    return (
                      <li key={`${name}-${index}`} className="rounded-lg border bg-card p-3">
                        <p className="text-sm font-semibold">{String(name)}</p>
                        <p className="text-xs text-muted-foreground">
                          {artists ? `${artists} • ` : ''}
                          {album?.name ? String(album.name) : 'Unbekanntes Album'}
                        </p>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </CardContent>
          </Card>
        </div>
      </TabsContent>
      <TabsContent value="settings">
        <Card>
          <CardHeader>
            <CardTitle>Spotify Konfiguration</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={form.handleSubmit(handleSubmit)}>
              {SPOTIFY_FIELDS.map((field) => (
                <div className="grid gap-2" key={field.key}>
                  <Label htmlFor={field.key}>{field.label}</Label>
                  <Input id={field.key} {...form.register(field.key)} placeholder={`Wert für ${field.label}`} />
                </div>
              ))}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => form.reset(defaultValues)}>
                  Zurücksetzen
                </Button>
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Speichern
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
};

export default SpotifyPage;
