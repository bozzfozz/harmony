import { useCallback, useEffect, useMemo, useState } from "react";
import { Album, Disc3, Library, Loader2, Settings2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useToast } from "../components/ui/use-toast";
import { useGlobalSearch } from "../hooks/useGlobalSearch";
import plexService, { PlexAlbum, PlexArtist, PlexStatus, PlexTrack } from "../services/plex";
import settingsService, { defaultSettings, type SettingsPayload } from "../services/settings";
import type { ServiceFilters } from "../components/AppHeader";

interface PlexPageProps {
  filters: ServiceFilters;
}

const PlexPage = ({ filters }: PlexPageProps) => {
  const { toast } = useToast();
  const { term } = useGlobalSearch();
  const [status, setStatus] = useState<PlexStatus | null>(null);
  const [artists, setArtists] = useState<PlexArtist[]>([]);
  const [albums, setAlbums] = useState<PlexAlbum[]>([]);
  const [tracks, setTracks] = useState<PlexTrack[]>([]);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [settings, setSettings] = useState<SettingsPayload>(defaultSettings);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    if (!filters.plex) return;
    try {
      setOverviewLoading(true);
      const [loadedStatus, loadedArtists, loadedAlbums, loadedTracks] = await Promise.all([
        plexService.getStatus(),
        plexService.getArtists(),
        plexService.getAlbums(),
        plexService.getTracks()
      ]);
      setStatus(loadedStatus);
      setArtists(loadedArtists);
      setAlbums(loadedAlbums);
      setTracks(loadedTracks);
    } catch (error) {
      console.error(error);
      toast({
        title: "Plex konnte nicht geladen werden",
        description: "Bibliothek und Status stehen aktuell nicht zur Verfügung.",
        variant: "destructive"
      });
    } finally {
      setOverviewLoading(false);
    }
  }, [filters.plex, toast]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

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

  const filteredArtists = useMemo(() => {
    if (!term) return artists;
    return artists.filter((artist) => artist.name.toLowerCase().includes(term.toLowerCase()));
  }, [artists, term]);

  const filteredAlbums = useMemo(() => {
    if (!term) return albums;
    return albums.filter((album) => album.title.toLowerCase().includes(term.toLowerCase()));
  }, [albums, term]);

  const filteredTracks = useMemo(() => {
    if (!term) return tracks;
    return tracks.filter((track) => track.title.toLowerCase().includes(term.toLowerCase()));
  }, [tracks, term]);

  const handleSettingsChange = (key: keyof SettingsPayload, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setSettingsSaving(true);
      setSettingsError(null);
      await settingsService.saveSettings(settings);
      toast({ title: "Einstellungen gespeichert", description: "Plex-Konfiguration aktualisiert." });
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

  if (!filters.plex) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Plex ausgeblendet</CardTitle>
          <CardDescription>Aktiviere den Plex-Filter im Header, um Inhalte zu sehen.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Plex</h1>
        <p className="text-sm text-muted-foreground">
          Überblick über Künstler, Alben und Tracks deiner Plex-Bibliothek sowie Zugangsdaten für den Server.
        </p>
      </header>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Bibliothek</TabsTrigger>
          <TabsTrigger value="settings">Einstellungen</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Library className="h-4 w-4" /> Bibliotheksstatus
              </CardTitle>
              <CardDescription>
                {status?.scanning ? "Scan läuft" : status?.lastScan ? `Letzter Scan: ${status.lastScan}` : "–"}
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Artists</p>
                <p className="mt-1 text-sm font-medium">{artists.length}</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Alben</p>
                <p className="mt-1 text-sm font-medium">{albums.length}</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Tracks</p>
                <p className="mt-1 text-sm font-medium">{tracks.length}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Album className="h-4 w-4" /> Artists & Alben
              </CardTitle>
              <CardDescription>Gefiltert nach „{term || "—"}“.</CardDescription>
            </CardHeader>
            <CardContent>
              {overviewLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Bibliothek wird geladen …
                </div>
              ) : (
                <div className="grid gap-6 lg:grid-cols-2">
                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Artists</h3>
                    {filteredArtists.map((artist) => (
                      <div key={artist.id} className="rounded-lg border border-border/60 bg-card p-4">
                        <p className="font-medium leading-tight">{artist.name}</p>
                        {artist.albumCount !== undefined && (
                          <p className="text-xs text-muted-foreground">{artist.albumCount} Alben</p>
                        )}
                      </div>
                    ))}
                    {!filteredArtists.length && (
                      <p className="text-xs text-muted-foreground">Keine Künstler mit diesem Filter.</p>
                    )}
                  </div>
                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Alben</h3>
                    <div className="overflow-hidden rounded-lg border border-border/60">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Album</TableHead>
                            <TableHead>Artist</TableHead>
                            <TableHead className="text-right">Jahr</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filteredAlbums.map((album) => (
                            <TableRow key={album.id}>
                              <TableCell className="font-medium">{album.title}</TableCell>
                              <TableCell>{album.artist}</TableCell>
                              <TableCell className="text-right text-sm text-muted-foreground">
                                {album.year ?? "–"}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    {!filteredAlbums.length && (
                      <p className="text-xs text-muted-foreground">Keine Alben mit diesem Filter.</p>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Disc3 className="h-4 w-4" /> Tracks
              </CardTitle>
              <CardDescription>Detailansicht der zuletzt synchronisierten Tracks.</CardDescription>
            </CardHeader>
            <CardContent>
              {overviewLoading ? (
                <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Tracks werden geladen …
                </div>
              ) : filteredTracks.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Titel</TableHead>
                        <TableHead>ID</TableHead>
                        <TableHead className="text-right">Dauer</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredTracks.slice(0, 20).map((track) => (
                        <TableRow key={track.id}>
                          <TableCell className="font-medium">{track.title}</TableCell>
                          <TableCell>{track.id}</TableCell>
                          <TableCell className="text-right text-sm text-muted-foreground">
                            {track.duration ? `${Math.round(track.duration / 60)} min` : "–"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
                  Keine Tracks gefunden.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="settings">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Settings2 className="h-4 w-4" /> Plex Einstellungen
              </CardTitle>
              <CardDescription>Basis-URL, Token und Bibliothek für deinen Plex-Server.</CardDescription>
            </CardHeader>
            <CardContent>
              {settingsLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Einstellungen werden geladen …
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="plex-base-url">Base URL</Label>
                    <Input
                      id="plex-base-url"
                      value={settings.plexBaseUrl}
                      onChange={(event) => handleSettingsChange("plexBaseUrl", event.target.value)}
                      placeholder="https://plex.example.com"
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="plex-token">Token</Label>
                    <Input
                      id="plex-token"
                      value={settings.plexToken}
                      onChange={(event) => handleSettingsChange("plexToken", event.target.value)}
                      placeholder="PLEX_TOKEN"
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="plex-library">Library</Label>
                    <Input
                      id="plex-library"
                      value={settings.plexLibrary}
                      onChange={(event) => handleSettingsChange("plexLibrary", event.target.value)}
                      placeholder="Music"
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

export default PlexPage;
