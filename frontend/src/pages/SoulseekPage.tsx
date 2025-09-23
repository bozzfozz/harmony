import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Loader2, Search as SearchIcon, Settings2 } from "lucide-react";

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
import soulseekService, { SoulseekDownload, SoulseekSearchResult } from "../services/soulseek";
import settingsService, { defaultSettings, type SettingsPayload } from "../services/settings";
import type { ServiceFilters } from "../components/AppHeader";

interface SoulseekPageProps {
  filters: ServiceFilters;
}

const SoulseekPage = ({ filters }: SoulseekPageProps) => {
  const { toast } = useToast();
  const { term } = useGlobalSearch();
  const debouncedSearch = useDebouncedValue(term, 400);
  const [downloads, setDownloads] = useState<SoulseekDownload[]>([]);
  const [searchResults, setSearchResults] = useState<SoulseekSearchResult[]>([]);
  const [loadingDownloads, setLoadingDownloads] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);
  const [settings, setSettings] = useState<SettingsPayload>(defaultSettings);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const loadDownloads = useCallback(async () => {
    if (!filters.soulseek) return;
    try {
      setLoadingDownloads(true);
      const data = await soulseekService.getDownloads();
      setDownloads(data);
    } catch (error) {
      console.error(error);
      toast({
        title: "Downloads konnten nicht geladen werden",
        description: "Soulseek-Status steht aktuell nicht zur Verfügung.",
        variant: "destructive"
      });
    } finally {
      setLoadingDownloads(false);
    }
  }, [filters.soulseek, toast]);

  useEffect(() => {
    void loadDownloads();
  }, [loadDownloads]);

  useEffect(() => {
    let active = true;

    const runSearch = async () => {
      if (!filters.soulseek || !debouncedSearch) {
        setSearchResults([]);
        return;
      }
      try {
        setSearchLoading(true);
        const results = await soulseekService.search(debouncedSearch);
        if (active) {
          setSearchResults(results);
          if (results.length) {
            toast({
              title: "Soulseek-Suche",
              description: `${results.length} Ergebnisse gefunden.`,
              duration: 2500
            });
          }
        }
      } catch (error) {
        console.error(error);
        if (active) {
          toast({
            title: "Suche fehlgeschlagen",
            description: "Bitte versuche es erneut.",
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
  }, [debouncedSearch, filters.soulseek, toast]);

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

  const filteredDownloads = useMemo(() => {
    if (!term) return downloads;
    return downloads.filter((download) => download.filename.toLowerCase().includes(term.toLowerCase()));
  }, [downloads, term]);

  const handleSettingsChange = (key: keyof SettingsPayload, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setSettingsSaving(true);
      setSettingsError(null);
      await settingsService.saveSettings(settings);
      toast({ title: "Einstellungen gespeichert", description: "Soulseek-Konfiguration aktualisiert." });
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

  const handleCancelDownload = async (downloadId: string) => {
    try {
      await soulseekService.cancelDownload(downloadId);
      toast({ title: "Download abgebrochen", description: "Der Download wurde gestoppt." });
      void loadDownloads();
    } catch (error) {
      console.error(error);
      toast({
        title: "Abbruch fehlgeschlagen",
        description: "Der Download konnte nicht gestoppt werden.",
        variant: "destructive"
      });
    }
  };

  if (!filters.soulseek) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Soulseek ausgeblendet</CardTitle>
          <CardDescription>Aktiviere den Soulseek-Filter im Header, um Inhalte zu sehen.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Soulseek</h1>
        <p className="text-sm text-muted-foreground">
          Überwache aktive Downloads, starte neue Suchen und verwalte deine Soulseek-Integration.
        </p>
      </header>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Downloads & Suche</TabsTrigger>
          <TabsTrigger value="settings">Einstellungen</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Download className="h-4 w-4" /> Aktuelle Downloads
              </CardTitle>
              <CardDescription>Gefiltert nach „{term || "—"}“.</CardDescription>
            </CardHeader>
            <CardContent>
              {loadingDownloads ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Downloads werden geladen …
                </div>
              ) : filteredDownloads.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Datei</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="w-[160px]">Fortschritt</TableHead>
                        <TableHead>Geschwindigkeit</TableHead>
                        <TableHead className="text-right">Aktion</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredDownloads.map((download) => (
                        <TableRow key={download.id}>
                          <TableCell className="font-medium">{download.filename}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="capitalize">
                              {download.status}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                                <div
                                  className="h-full rounded-full bg-primary transition-all"
                                  style={{ width: `${Math.min(100, Math.max(0, download.progress))}%` }}
                                />
                              </div>
                              <span className="w-10 text-xs text-muted-foreground">{Math.round(download.progress)}%</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {download.speed ? `${download.speed} kb/s` : "–"}
                          </TableCell>
                          <TableCell className="text-right">
                            {download.status === "downloading" || download.status === "queued" ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => void handleCancelDownload(download.id)}
                              >
                                Abbrechen
                              </Button>
                            ) : (
                              <span className="text-xs text-muted-foreground">–</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
                  Keine Downloads gefunden.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <SearchIcon className="h-4 w-4" /> Suchergebnisse
              </CardTitle>
              <CardDescription>Ergebnisse der globalen Suche in Soulseek.</CardDescription>
            </CardHeader>
            <CardContent>
              {searchLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Suche läuft …
                </div>
              ) : searchResults.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Datei</TableHead>
                        <TableHead>Benutzer</TableHead>
                        <TableHead className="text-right">Größe</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {searchResults.slice(0, 25).map((result) => (
                        <TableRow key={result.id}>
                          <TableCell className="font-medium">{result.filename}</TableCell>
                          <TableCell>{result.user}</TableCell>
                          <TableCell className="text-right text-sm text-muted-foreground">
                            {Math.round(result.size / (1024 * 1024))} MB
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
                  Keine Suchergebnisse vorhanden.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="settings">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Settings2 className="h-4 w-4" /> Soulseek Einstellungen
              </CardTitle>
              <CardDescription>API-Endpunkt und Schlüssel für deinen Soulseek-Dienst.</CardDescription>
            </CardHeader>
            <CardContent>
              {settingsLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Einstellungen werden geladen …
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="soulseek-url">SLSKD URL</Label>
                    <Input
                      id="soulseek-url"
                      value={settings.soulseekApiUrl}
                      onChange={(event) => handleSettingsChange("soulseekApiUrl", event.target.value)}
                      placeholder="https://slsd.example.com"
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="soulseek-api-key">API Key</Label>
                    <Input
                      id="soulseek-api-key"
                      value={settings.soulseekApiKey}
                      onChange={(event) => handleSettingsChange("soulseekApiKey", event.target.value)}
                      placeholder="SLSKD_API_KEY"
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

export default SoulseekPage;
