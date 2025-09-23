import { Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { useQuery } from '../lib/query';
import { fetchSpotifyOverview } from '../lib/api';
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
  { key: 'spotify.clientId', label: 'Client ID', placeholder: 'Client ID' },
  { key: 'spotify.clientSecret', label: 'Client secret', placeholder: 'Client secret' },
  { key: 'spotify.redirectUri', label: 'Redirect URI', placeholder: 'https://example.com/callback' }
] as const;

const SpotifyPage = () => {
  const overviewQuery = useQuery({
    queryKey: ['spotify-overview'],
    queryFn: fetchSpotifyOverview,
    refetchInterval: 60000
  });

  const { form, onSubmit, handleReset, isSaving, isLoading } = useServiceSettingsForm({
    fields: settingsFields,
    loadErrorDescription: 'Spotify settings could not be loaded.',
    successTitle: 'Spotify settings saved',
    errorTitle: 'Failed to save Spotify settings'
  });

  const overview = overviewQuery.data ?? {
    playlists: 0,
    artists: 0,
    tracks: 0,
    lastSync: ''
  };

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <Card>
          <CardHeader>
            <CardTitle>Spotify library</CardTitle>
          </CardHeader>
          <CardContent>
            {overviewQuery.isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Playlists</p>
                  <p className="mt-2 text-2xl font-semibold">{overview.playlists}</p>
                </div>
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Artists</p>
                  <p className="mt-2 text-2xl font-semibold">{overview.artists}</p>
                </div>
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Tracks</p>
                  <p className="mt-2 text-2xl font-semibold">{overview.tracks}</p>
                </div>
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Last sync</p>
                  <p className="mt-2 text-base font-semibold">{formatDateTime(overview.lastSync)}</p>
                </div>
              </div>
            )}
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
