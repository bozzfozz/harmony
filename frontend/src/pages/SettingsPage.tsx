import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Input,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger
} from '../components/ui/shadcn';
import { Label } from '../components/ui/label';
import useServiceSettingsForm from '../hooks/useServiceSettingsForm';
import { useToast } from '../hooks/useToast';
import {
  ApiError,
  getSpotifyMode,
  setSpotifyMode,
  testServiceConnection,
  type ServiceIdentifier,
  type SpotifyMode
} from '../lib/api';

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

const maskedKeys = new Set(['SPOTIFY_CLIENT_SECRET', 'PLEX_TOKEN', 'SLSKD_API_KEY']);

const SERVICE_LABELS: Record<ServiceIdentifier, string> = {
  spotify: 'Spotify',
  plex: 'Plex',
  soulseek: 'Soulseek'
};

const SettingsPage = () => {
  const { toast } = useToast();
  const [spotifyMode, setSpotifyModeState] = useState<SpotifyMode>('PRO');
  const [isModeLoading, setIsModeLoading] = useState(true);
  const [isModeUpdating, setIsModeUpdating] = useState(false);
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

  const [isTesting, setIsTesting] = useState<Record<ServiceIdentifier, boolean>>({
    spotify: false,
    plex: false,
    soulseek: false
  });

  useEffect(() => {
    const fetchMode = async () => {
      try {
        const response = await getSpotifyMode();
        setSpotifyModeState(response.mode);
      } catch (error) {
        if (error instanceof ApiError && !error.handled) {
          toast({
            title: 'Spotify-Modus',
            description: error.message,
            variant: 'destructive'
          });
          error.markHandled();
        }
      } finally {
        setIsModeLoading(false);
      }
    };
    fetchMode();
  }, [toast]);

  const updateMode = async (mode: SpotifyMode) => {
    if (mode === spotifyMode) {
      return;
    }
    setIsModeUpdating(true);
    try {
      await setSpotifyMode(mode);
      setSpotifyModeState(mode);
      toast({
        title: 'Spotify-Modus gespeichert',
        description: mode === 'FREE' ? 'FREE-Modus ist aktiv.' : 'PRO-Modus ist aktiv.'
      });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Moduswechsel fehlgeschlagen.';
      toast({ title: 'Spotify-Modus', description: message, variant: 'destructive' });
    } finally {
      setIsModeUpdating(false);
    }
  };

  const handleTestConnection = async (service: ServiceIdentifier) => {
    setIsTesting((previous) => ({ ...previous, [service]: true }));
    const label = SERVICE_LABELS[service];
    try {
      const result = await testServiceConnection(service);
      if (result.status === 'ok') {
        const optionalHint =
          result.optional_missing.length > 0
            ? `Optional: ${result.optional_missing.join(', ')}`
            : undefined;
        toast({
          title: `✅ ${label}-Verbindung erfolgreich`,
          description: optionalHint
        });
      } else {
        const missingKeys = result.missing.length > 0 ? result.missing.join(', ') : 'Unbekannte Einstellungen';
        const optionalKeys = result.optional_missing.length > 0 ? ` Optional: ${result.optional_missing.join(', ')}` : '';
        toast({
          title: `❌ ${label}-Verbindung fehlgeschlagen`,
          description: `Fehlende Werte: ${missingKeys}.${optionalKeys}`.trim(),
          variant: 'destructive'
        });
      }
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 503) {
          if (!error.handled) {
            toast({
              title: `❌ ${label}-Zugangsdaten erforderlich`,
              description: 'Bitte ergänzen Sie die Credentials im entsprechenden Tab.',
              variant: 'destructive'
            });
          }
          error.markHandled();
          return;
        }
      if (error.handled) {
        return;
      }
      error.markHandled();
    }
    toast({
        title: `❌ ${label}-Verbindung konnte nicht geprüft werden`,
        description: 'Der Health-Endpoint ist derzeit nicht erreichbar.',
        variant: 'destructive'
      });
    } finally {
      setIsTesting((previous) => ({ ...previous, [service]: false }));
    }
  };

  return (
    <Tabs defaultValue="spotify">
      <TabsList>
        <TabsTrigger value="spotify">Spotify</TabsTrigger>
        <TabsTrigger value="plex">Plex</TabsTrigger>
        <TabsTrigger value="soulseek">Soulseek</TabsTrigger>
      </TabsList>
      <TabsContent value="spotify">
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Moduswahl</CardTitle>
            <CardDescription>Wechsle zwischen Spotify FREE und PRO direkt aus den Einstellungen.</CardDescription>
          </CardHeader>
          <CardContent>
            {isModeLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Lade aktuellen Modus …
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant={spotifyMode === 'FREE' ? 'default' : 'outline'}
                  disabled={isModeUpdating}
                  onClick={() => updateMode('FREE')}
                >
                  Spotify FREE
                </Button>
                <Button
                  type="button"
                  variant={spotifyMode === 'PRO' ? 'default' : 'outline'}
                  disabled={isModeUpdating}
                  onClick={() => updateMode('PRO')}
                >
                  Spotify PRO
                </Button>
                <span className="text-xs text-muted-foreground">Aktuell: {spotifyMode}</span>
              </div>
            )}
          </CardContent>
        </Card>
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
                    <Input
                      id={key}
                      type={maskedKeys.has(key) ? 'password' : 'text'}
                      autoComplete="off"
                      placeholder={placeholder}
                      {...spotify.form.register(key)}
                    />
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
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => handleTestConnection('spotify')}
                  disabled={spotify.isSaving || isTesting.spotify}
                >
                  {isTesting.spotify ? 'Teste…' : 'Verbindung testen'}
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
                    <Input
                      id={key}
                      type={maskedKeys.has(key) ? 'password' : 'text'}
                      autoComplete="off"
                      placeholder={placeholder}
                      {...plex.form.register(key)}
                    />
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
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => handleTestConnection('plex')}
                  disabled={plex.isSaving || isTesting.plex}
                >
                  {isTesting.plex ? 'Teste…' : 'Verbindung testen'}
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
                    <Input
                      id={key}
                      type={maskedKeys.has(key) ? 'password' : 'text'}
                      autoComplete="off"
                      placeholder={placeholder}
                      {...soulseek.form.register(key)}
                    />
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
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => handleTestConnection('soulseek')}
                  disabled={soulseek.isSaving || isTesting.soulseek}
                >
                  {isTesting.soulseek ? 'Teste…' : 'Verbindung testen'}
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
