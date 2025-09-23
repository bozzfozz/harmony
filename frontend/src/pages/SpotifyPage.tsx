import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, ListMusic, Music, Settings2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useToast } from "../components/ui/use-toast";
import useDebouncedValue from "../hooks/useDebouncedValue";
import { useGlobalSearch } from "../hooks/useGlobalSearch";
import spotifyService, { SpotifyPlaylist, SpotifyStatus, SpotifyTrack } from "../services/spotify";
import settingsService, { defaultSettings, type SettingsPayload } from "../services/settings";
import type { ServiceFilters } from "../components/AppHeader";

type SearchResults = {
  tracks: SpotifyTrack[];
};

interface SpotifyPageProps {
  filters: ServiceFilters;
}

const SpotifyPage = ({ filters }: SpotifyPageProps) => {
  const { toast } = useToast();
  const { term } = useGlobalSearch();
  const debouncedSearch = useDebouncedValue(term, 400);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);
  const [status, setStatus] = useState<SpotifyStatus | null>(null);
  const [playlists, setPlaylists] = useState<SpotifyPlaylist[]>([]);
  const [searchResults, setSearchResults] = useState<SearchResults>({ tracks: [] });
  const [settings, setSettings] = useState<SettingsPayload>(defaultSettings);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    if (!filters.spotify) return;
    try {
      setOverviewLoading(true);
      const [loadedStatus, loadedPlaylists] = await Promise.all([
        spotifyService.getStatus(),
        spotifyService.getPlaylists()
      ]);
      setStatus(loadedStatus);
      setPlaylists(loadedPlaylists);
    } catch (error) {
      console.error(error);
      toast({
        title: "Spotify konnte nicht geladen werden",
        description: "Status und Playlists stehen aktuell nicht zur Verfügung.",
        variant: "destructive"
      });
    } finally {
      setOverviewLoading(false);
    }
  }, [filters.spotify, toast]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    let active = true;

    const runSearch = async () => {
      if (!filters.spotify || !debouncedSearch) {
        setSearchResults({ tracks: [] });
        return;
      }
      try {
        setSearchLoading(true);
        const tracks = await spotifyService.searchTracks(debouncedSearch);
        if (active) {
          setSearchResults({ tracks });
          if (tracks.length) {
            toast({
              title: "Spotify-Suche",
              description: `${tracks.length} Tracks gefunden.`,
              duration: 2500
            });
          }
        }
      } catch (error) {
        console.error(error);
        if (active) {
          toast({
            title: "Suche fehlgeschlagen",
            description: "Die Spotify-Suche konnte nicht durchgeführt werden.",
            variant: "destructive"
          });
        }
      } finally {
        if (active) {
          setSearchLoading(false);
        }
      }
    };

    void runSearch();
    return () => {
      active = false;
    };
  }, [debouncedSearch, filters.spotify, toast]);

  useEffect(() => {
    let mounted = true;
    const loadSettings = async () => {
      try {
        setSettingsLoading(true);
        const loaded = await settingsService.getSettings();
        if (mounted) {
          setSettings(loaded);
        }
      } catch (error) {
        console.error(error);
        if (mounted) {
          setSettingsError("Einstellungen konnten nicht geladen werden.");
        }
      } finally {
        if (mounted) {
          setSettingsLoading(false);
        }
      }
    };

    void loadSettings();
    return () => {
      mounted = false;
    };
  }, []);

  const filteredPlaylists = useMemo(() => {
    if (!term) return playlists;
    return playlists.filter((playlist) => playlist.name.toLowerCase().includes(term.toLowerCase()));
  }, [playlists, term]);

  const handleSettingsChange = (key: keyof SettingsPayload, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setSettingsSaving(true);
      setSettingsError(null);
      await settingsService.saveSettings(settings);
      toast({ title: "Einstellungen gespeichert", description: "Spotify-Konfiguration aktualisiert." });
    } catch (error) {
      console.error(error);
      setSettingsError("Fehler beim Speichern der Einstellungen.");
      toast({
        title: "Speichern fehlgeschlagen",
        description: "Bitte versuche es erneut.",
        variant: "destructive"
      });
    } finally {
      setSettingsSaving(false);
    }
  };

  if (!filters.spotify) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Spotify ausgeblendet</CardTitle>
          <CardDescription>Aktiviere den Spotify-Filter im Header, um Inhalte zu sehen.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Spotify</h1>
        <p className="text-sm text-muted-foreground">
          Suche nach Tracks und verwalte Playlists. Spotify-Credentials können direkt in Harmony gepflegt werden.
        </p>
      </header>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Status & Playlists</TabsTrigger>
          <TabsTrigger value="settings">Einstellungen</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Music className="h-4 w-4" /> Spotify Status
              </CardTitle>
              <CardDescription>Verbunden seit: {status?.lastSync ?? "–"}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Verbindung</p>
                <p className="mt-1 flex items-center gap-2 text-sm font-medium">
                  <Badge variant={status?.connected ? "secondary" : "destructive"}>
                    {status?.connected ? "Connected" : "Disconnected"}
                  </Badge>
                </p>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Playlists</p>
                <p className="mt-1 text-sm font-medium">{playlists.length}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ListMusic className="h-4 w-4" /> Playlists & Suche
              </CardTitle>
              <CardDescription>
                Ergebnisse für „{debouncedSearch || term || "—"}". Die globale Suche filtert Playlists und Tracks.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {overviewLoading ? (
                <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Playlists werden geladen …
                </div>
              ) : (
                <div className="grid gap-6 lg:grid-cols-2">
                  <div>
                    <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Playlists</h3>
                    <div className="space-y-3">
                      {filteredPlaylists.map((playlist) => (
                        <div key={playlist.id} className="rounded-lg border border-border/60 bg-card p-4">
                          <p className="font-medium leading-tight">{playlist.name}</p>
                          <p className="text-xs text-muted-foreground">{playlist.trackCount} Tracks</p>
                          {playlist.description && (
                            <p className="mt-2 text-xs text-muted-foreground">{playlist.description}</p>
                          )}
                        </div>
                      ))}
                      {!filteredPlaylists.length && (
                        <p className="text-xs text-muted-foreground">Keine Playlists mit diesem Filter.</p>
                      )}
                    </div>
                  </div>
                  <div>
                    <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Tracks</h3>
                    {searchLoading ? (
                      <div className="flex items-center justify-center rounded-md border border-dashed border-border py-10 text-sm text-muted-foreground">
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Suche läuft …
                      </div>
                    ) : searchResults.tracks.length ? (
                      <div className="overflow-hidden rounded-lg border border-border/60">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Track</TableHead>
                              <TableHead>Artist</TableHead>
                              <TableHead>Album</TableHead>
                              <TableHead className="text-right">Dauer</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {searchResults.tracks.map((track) => (
                              <TableRow key={track.id}>
                                <TableCell className="font-medium">{track.name}</TableCell>
                                <TableCell>{track.artist}</TableCell>
                                <TableCell>{track.album}</TableCell>
                                <TableCell className="text-right text-sm text-muted-foreground">
                                  {Math.round(track.durationMs / 1000)}s
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    ) : (
                      <p className="rounded-md border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
                        Keine Tracks gefunden.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="settings">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Settings2 className="h-4 w-4" /> Spotify Einstellungen
              </CardTitle>
              <CardDescription>API-Zugänge für Spotify. Daten werden nach dem Speichern direkt übernommen.</CardDescription>
            </CardHeader>
            <CardContent>
              {settingsLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Einstellungen werden geladen …
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-6">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="spotify-client-id">Client ID</Label>
                      <Input
                        id="spotify-client-id"
                        value={settings.spotifyClientId}
                        onChange={(event) => handleSettingsChange("spotifyClientId", event.target.value)}
                        placeholder="SPOTIFY_CLIENT_ID"
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="spotify-client-secret">Client Secret</Label>
                      <Input
                        id="spotify-client-secret"
                        value={settings.spotifyClientSecret}
                        onChange={(event) => handleSettingsChange("spotifyClientSecret", event.target.value)}
                        placeholder="SPOTIFY_CLIENT_SECRET"
                        required
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="spotify-redirect-uri">Redirect URI</Label>
                    <Input
                      id="spotify-redirect-uri"
                      value={settings.spotifyRedirectUri}
                      onChange={(event) => handleSettingsChange("spotifyRedirectUri", event.target.value)}
                      placeholder="https://example.com/callback"
                      required
                    />
                  </div>
                  {settingsError && <p className="text-sm text-destructive">{settingsError}</p>}
                  <div className="flex justify-end gap-2">
                    <Button type="submit" disabled={settingsSaving}>
                      {settingsSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Einstellungen speichern
                    </Button>
                  </div>
                </form>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default SpotifyPage;
