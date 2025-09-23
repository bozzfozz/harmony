import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useToast } from "../components/ui/use-toast";
import settingsService, { SettingsPayload } from "../services/settings";

const initialState: SettingsPayload = {
  spotifyClientId: "",
  spotifyClientSecret: "",
  spotifyRedirectUri: "",
  plexBaseUrl: "",
  plexToken: "",
  plexLibrary: "",
  soulseekApiUrl: "",
  soulseekApiKey: ""
};

const Settings = () => {
  const { toast } = useToast();
  const [formState, setFormState] = useState<SettingsPayload>(initialState);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const data = await settingsService.getSettings();
        setFormState((current) => ({ ...current, ...data }));
      } catch (error) {
        console.error(error);
        toast({
          title: "Einstellungen konnten nicht geladen werden",
          variant: "destructive"
        });
      } finally {
        setLoading(false);
      }
    };

    void fetchSettings();
  }, [toast]);

  const handleChange = (field: keyof SettingsPayload) => (event: ChangeEvent<HTMLInputElement>) => {
    setFormState((current) => ({ ...current, [field]: event.target.value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setSaving(true);
      await settingsService.saveSettings(formState);
      toast({ title: "Einstellungen gespeichert" });
    } catch (error) {
      console.error(error);
      toast({
        title: "Speichern fehlgeschlagen",
        variant: "destructive"
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Einstellungen</h1>
        <p className="text-sm text-muted-foreground">
          Verwalte API-Zugänge und Konfigurationswerte für alle Dienste.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Verbindungen</CardTitle>
          <CardDescription>Trage die Zugangsdaten für Spotify, Plex und Soulseek ein.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" onSubmit={handleSubmit}>
            <fieldset className="space-y-4" disabled={loading}>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="spotifyClientId">Spotify Client ID</Label>
                  <Input
                    id="spotifyClientId"
                    value={formState.spotifyClientId}
                    onChange={handleChange("spotifyClientId")}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="spotifyClientSecret">Spotify Client Secret</Label>
                  <Input
                    id="spotifyClientSecret"
                    type="password"
                    value={formState.spotifyClientSecret}
                    onChange={handleChange("spotifyClientSecret")}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="spotifyRedirectUri">Spotify Redirect URI</Label>
                  <Input
                    id="spotifyRedirectUri"
                    value={formState.spotifyRedirectUri}
                    onChange={handleChange("spotifyRedirectUri")}
                    placeholder="https://example.com/callback"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="plexBaseUrl">Plex Base URL</Label>
                  <Input
                    id="plexBaseUrl"
                    value={formState.plexBaseUrl}
                    onChange={handleChange("plexBaseUrl")}
                    placeholder="http://localhost:32400"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="plexToken">Plex Token</Label>
                  <Input
                    id="plexToken"
                    value={formState.plexToken}
                    onChange={handleChange("plexToken")}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="plexLibrary">Plex Library</Label>
                  <Input
                    id="plexLibrary"
                    value={formState.plexLibrary}
                    onChange={handleChange("plexLibrary")}
                    placeholder="Music"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="soulseekApiUrl">Soulseek API URL</Label>
                  <Input
                    id="soulseekApiUrl"
                    value={formState.soulseekApiUrl}
                    onChange={handleChange("soulseekApiUrl")}
                    placeholder="http://localhost:5030"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="soulseekApiKey">Soulseek API Key</Label>
                  <Input
                    id="soulseekApiKey"
                    value={formState.soulseekApiKey}
                    onChange={handleChange("soulseekApiKey")}
                    required
                  />
                </div>
              </div>
            </fieldset>

            <div className="flex items-center justify-end">
              <Button type="submit" disabled={saving || loading}>
                {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Speichern
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default Settings;
