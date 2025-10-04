import { useEffect, useState } from 'react';
import { Loader2, ShieldAlert } from 'lucide-react';
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
import AuthKeyPanel from './Settings/AuthKeyPanel';
import SecretsPanel from './Settings/SecretsPanel';
import { ApiError } from '../api/client';
import { getSpotifyStatus } from '../api/services/spotify';
import { testServiceConnection } from '../api/services/system';
import type { ServiceIdentifier } from '../api/types';
import type { SpotifyStatusResponse } from '../api/types';

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
  const [spotifyStatus, setSpotifyStatus] = useState<SpotifyStatusResponse | null>(null);
  const [isStatusLoading, setIsStatusLoading] = useState(true);
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
    const fetchStatus = async () => {
      try {
        const response = await getSpotifyStatus();
        setSpotifyStatus(response);
      } catch (error) {
        if (error instanceof ApiError && !error.handled) {
          toast({
            title: 'Spotify-Status',
            description: error.message,
            variant: 'destructive'
          });
          error.markHandled();
        }
      } finally {
        setIsStatusLoading(false);
      }
    };
    fetchStatus();
  }, [toast]);

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
    <div className="space-y-6">
      <AuthKeyPanel />
      <SecretsPanel />
      <Tabs defaultValue="spotify">
      <TabsList>
        <TabsTrigger value="spotify">Spotify</TabsTrigger>
        <TabsTrigger value="plex">Plex</TabsTrigger>
        <TabsTrigger value="soulseek">Soulseek</TabsTrigger>
      </TabsList>
      <TabsContent value="spotify">
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Spotify Status</CardTitle>
            <CardDescription>Überprüfe die Verfügbarkeit der PRO-Anbindung und vorhandene Sessions.</CardDescription>
          </CardHeader>
          <CardContent>
            {isStatusLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Lade Status …
              </div>
            ) : spotifyStatus ? (
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <ShieldAlert className="h-5 w-5 text-indigo-600" />
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      Verbindungsstatus: {spotifyStatus.status === 'connected' ? 'Verbunden' : spotifyStatus.status === 'unauthenticated' ? 'Nicht authentifiziert' : 'Nicht konfiguriert'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      FREE-Import ist immer verfügbar. PRO-Funktionen benötigen gültige Spotify-Credentials.
                    </p>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-md border border-border p-3 text-sm">
                    <p className="font-medium text-foreground">PRO verfügbar</p>
                    <p className="text-muted-foreground">
                      {spotifyStatus.pro_available ? 'Ja – Credentials erkannt.' : 'Nein – Zugangsdaten fehlen.'}
                    </p>
                  </div>
                  <div className="rounded-md border border-border p-3 text-sm">
                    <p className="font-medium text-foreground">Authentifiziert</p>
                    <p className="text-muted-foreground">
                      {spotifyStatus.authenticated ? 'Aktive Session vorhanden.' : 'Noch kein OAuth-Login.'}
                    </p>
                  </div>
                </div>
                {!spotifyStatus.pro_available && (
                  <p className="text-sm text-amber-600 dark:text-amber-400">
                    Hinterlege Client-ID, Client-Secret und Redirect-URI, um PRO-Funktionen freizuschalten.
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Statusinformationen sind derzeit nicht verfügbar.</p>
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
    </div>
  );
};

export default SettingsPage;
