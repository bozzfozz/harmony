import { Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle
} from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import useServiceSettingsForm from '../hooks/useServiceSettingsForm';

const spotifyFields = [
  { key: 'SPOTIFY_CLIENT_ID', label: 'Client ID', placeholder: 'Spotify client ID' },
  { key: 'SPOTIFY_CLIENT_SECRET', label: 'Client secret', placeholder: 'Spotify client secret' },
  { key: 'SPOTIFY_REDIRECT_URI', label: 'Redirect URI', placeholder: 'https://example.com/callback' }
] as const;

const plexFields = [
  { key: 'PLEX_BASE_URL', label: 'Base URL', placeholder: 'https://plex.example.com' },
  { key: 'PLEX_TOKEN', label: 'Access token', placeholder: 'Plex token' },
  { key: 'PLEX_LIBRARY', label: 'Library name', placeholder: 'Music' }
] as const;

const soulseekFields = [
  { key: 'SLSKD_URL', label: 'Daemon URL', placeholder: 'http://localhost:5030' },
  { key: 'SLSKD_API_KEY', label: 'API key', placeholder: 'Optional API key' }
] as const;

const SettingsPage = () => {
  const spotify = useServiceSettingsForm({
    fields: spotifyFields,
    loadErrorDescription: 'Spotify settings could not be loaded.',
    successTitle: 'Spotify settings saved',
    errorTitle: 'Failed to save Spotify settings'
  });

  const plex = useServiceSettingsForm({
    fields: plexFields,
    loadErrorDescription: 'Plex settings could not be loaded.',
    successTitle: 'Plex settings saved',
    errorTitle: 'Failed to save Plex settings'
  });

  const soulseek = useServiceSettingsForm({
    fields: soulseekFields,
    loadErrorDescription: 'Soulseek settings could not be loaded.',
    successTitle: 'Soulseek settings saved',
    errorTitle: 'Failed to save Soulseek settings'
  });

  return (
    <Tabs defaultValue="spotify">
      <TabsList>
        <TabsTrigger value="spotify">Spotify</TabsTrigger>
        <TabsTrigger value="plex">Plex</TabsTrigger>
        <TabsTrigger value="soulseek">Soulseek</TabsTrigger>
      </TabsList>
      <TabsContent value="spotify">
        <Card>
          <CardHeader>
            <CardTitle>Spotify configuration</CardTitle>
          </CardHeader>
          {spotify.isLoading ? (
            <CardContent>
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            </CardContent>
          ) : (
            <form onSubmit={spotify.onSubmit} className="space-y-6">
              <CardContent className="space-y-4">
                {spotifyFields.map(({ key, label, placeholder }) => (
                  <div key={key} className="space-y-2">
                    <Label htmlFor={key}>{label}</Label>
                    <Input id={key} placeholder={placeholder} {...spotify.form.register(key)} />
                  </div>
                ))}
              </CardContent>
              <CardFooter className="gap-2">
                <Button type="submit" disabled={spotify.isSaving}>
                  {spotify.isSaving ? 'Saving…' : 'Save changes'}
                </Button>
                <Button type="button" variant="outline" onClick={spotify.handleReset} disabled={spotify.isSaving}>
                  Reset
                </Button>
              </CardFooter>
            </form>
          )}
        </Card>
      </TabsContent>
      <TabsContent value="plex">
        <Card>
          <CardHeader>
            <CardTitle>Plex configuration</CardTitle>
          </CardHeader>
          {plex.isLoading ? (
            <CardContent>
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            </CardContent>
          ) : (
            <form onSubmit={plex.onSubmit} className="space-y-6">
              <CardContent className="space-y-4">
                {plexFields.map(({ key, label, placeholder }) => (
                  <div key={key} className="space-y-2">
                    <Label htmlFor={key}>{label}</Label>
                    <Input id={key} placeholder={placeholder} {...plex.form.register(key)} />
                  </div>
                ))}
              </CardContent>
              <CardFooter className="gap-2">
                <Button type="submit" disabled={plex.isSaving}>
                  {plex.isSaving ? 'Saving…' : 'Save changes'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={plex.handleReset}
                  disabled={plex.isSaving}
                >
                  Reset
                </Button>
              </CardFooter>
            </form>
          )}
        </Card>
      </TabsContent>
      <TabsContent value="soulseek">
        <Card>
          <CardHeader>
            <CardTitle>Soulseek configuration</CardTitle>
          </CardHeader>
          {soulseek.isLoading ? (
            <CardContent>
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            </CardContent>
          ) : (
            <form onSubmit={soulseek.onSubmit} className="space-y-6">
              <CardContent className="space-y-4">
                {soulseekFields.map(({ key, label, placeholder }) => (
                  <div key={key} className="space-y-2">
                    <Label htmlFor={key}>{label}</Label>
                    <Input id={key} placeholder={placeholder} {...soulseek.form.register(key)} />
                  </div>
                ))}
              </CardContent>
              <CardFooter className="gap-2">
                <Button type="submit" disabled={soulseek.isSaving}>
                  {soulseek.isSaving ? 'Saving…' : 'Save changes'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={soulseek.handleReset}
                  disabled={soulseek.isSaving}
                >
                  Reset
                </Button>
              </CardFooter>
            </form>
          )}
        </Card>
      </TabsContent>
    </Tabs>
  );
};

export default SettingsPage;
