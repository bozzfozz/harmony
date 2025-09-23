import { useCallback, useEffect, useMemo, useState } from "react";
import { Library, ListMusic, Loader2, Server, Settings2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useToast } from "../components/ui/use-toast";
import { useGlobalSearch } from "../hooks/useGlobalSearch";
import plexService, {
  PlexLibraryItem,
  PlexLibrarySection,
  PlexSession,
  PlexStatus
} from "../services/plex";
import settingsService, { defaultSettings, type SettingsPayload } from "../services/settings";
import type { ServiceFilters } from "../components/AppHeader";

interface PlexPageProps {
  filters: ServiceFilters;
}

const PlexPage = ({ filters }: PlexPageProps) => {
  const { toast } = useToast();
  const { term } = useGlobalSearch();
  const [status, setStatus] = useState<PlexStatus | null>(null);
  const [sections, setSections] = useState<PlexLibrarySection[]>([]);
  const [sessions, setSessions] = useState<PlexSession[]>([]);
  const [selectedSection, setSelectedSection] = useState<string | null>(null);
  const [sectionItems, setSectionItems] = useState<PlexLibraryItem[]>([]);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingSection, setLoadingSection] = useState(false);
  const [settings, setSettings] = useState<SettingsPayload>(defaultSettings);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    if (!filters.plex) return;
    try {
      setLoadingOverview(true);
      const [loadedStatus, loadedSections, loadedSessions] = await Promise.all([
        plexService.getStatus(),
        plexService.getSections(),
        plexService.getSessions()
      ]);
      setStatus(loadedStatus);
      setSections(loadedSections);
      setSessions(loadedSessions);
      if (!selectedSection && loadedSections.length) {
        setSelectedSection(loadedSections[0].id);
      }
    } catch (error) {
      console.error(error);
      toast({
        title: "Plex konnte nicht geladen werden",
        description: "Status und Bibliotheksübersicht stehen aktuell nicht zur Verfügung.",
        variant: "destructive"
      });
    } finally {
      setLoadingOverview(false);
    }
  }, [filters.plex, selectedSection, toast]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    let active = true;
    const fetchSettings = async () => {
      try {
        setSettingsLoading(true);
        const loaded = await settingsService.getSettings();
        if (active) {
          setSettings(loaded);
        }
      } catch (error) {
        console.error(error);
        if (active) {
          setSettingsError("Einstellungen konnten nicht geladen werden.");
        }
      } finally {
        if (active) {
          setSettingsLoading(false);
        }
      }
    };

    void fetchSettings();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedSection) return;
    let active = true;

    const loadSection = async () => {
      try {
        setLoadingSection(true);
        const items = await plexService.getSectionItems(selectedSection);
        if (active) {
          setSectionItems(items);
        }
      } catch (error) {
        console.error(error);
        if (active) {
          toast({
            title: "Sektion konnte nicht geladen werden",
            description: "Bitte versuche es erneut.",
            variant: "destructive"
          });
        }
      } finally {
        if (active) {
          setLoadingSection(false);
        }
      }
    };

    void loadSection();
    return () => {
      active = false;
    };
  }, [selectedSection, toast]);

  const filteredItems = useMemo(() => {
    if (!term) return sectionItems;
    const lower = term.toLowerCase();
    return sectionItems.filter((item) =>
      [item.title, item.parent, item.type, item.year?.toString()].some((value) =>
        value?.toLowerCase().includes(lower)
      )
    );
  }, [sectionItems, term]);

  const filteredSessions = useMemo(() => {
    if (!term) return sessions;
    const lower = term.toLowerCase();
    return sessions.filter((session) =>
      [session.title, session.user, session.state].some((value) =>
        value?.toLowerCase().includes(lower)
      )
    );
  }, [sessions, term]);

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
          Überblick über aktive Sitzungen und Bibliothekssektionen deines Plex-Servers.
        </p>
      </header>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Status & Bibliothek</TabsTrigger>
          <TabsTrigger value="settings">Einstellungen</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Server className="h-4 w-4" /> Serverstatus
              </CardTitle>
              <CardDescription>
                {status?.status === "connected" ? "Verbunden" : "Nicht verbunden"}
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Sitzungen</p>
                <p className="mt-1 text-sm font-medium">{sessions.length}</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Sektionen</p>
                <p className="mt-1 text-sm font-medium">{sections.length}</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-4">
                <p className="text-xs uppercase text-muted-foreground">Bibliothek</p>
                <p className="mt-1 text-sm font-medium">
                  {status?.library?.MediaContainer?.librarySections?.length ?? "–"}
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Library className="h-4 w-4" /> Bibliothekssektionen
              </CardTitle>
              <CardDescription>Wähle eine Sektion aus, um Einträge anzuzeigen.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {sections.map((section) => (
                  <Button
                    key={section.id}
                    variant={selectedSection === section.id ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSelectedSection(section.id)}
                  >
                    {section.title}
                  </Button>
                ))}
              </div>

              <div className="rounded-lg border border-border/60">
                {loadingSection ? (
                  <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Sektion wird geladen …
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Titel</TableHead>
                        <TableHead>Übergeordnet</TableHead>
                        <TableHead>Typ</TableHead>
                        <TableHead>Jahr</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredItems.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell>{item.title}</TableCell>
                          <TableCell>{item.parent ?? "—"}</TableCell>
                          <TableCell>{item.type ?? "—"}</TableCell>
                          <TableCell>{item.year ?? "—"}</TableCell>
                        </TableRow>
                      ))}
                      {!filteredItems.length && (
                        <TableRow>
                          <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                            Keine Einträge gefunden.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ListMusic className="h-4 w-4" /> Aktive Sitzungen
              </CardTitle>
              <CardDescription>Playback-Informationen für aktuelle Nutzer.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg border border-border/60">
                {loadingOverview ? (
                  <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Sitzungen werden geladen …
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Benutzer</TableHead>
                        <TableHead>Titel</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredSessions.map((session) => (
                        <TableRow key={session.id}>
                          <TableCell>{session.user ?? "—"}</TableCell>
                          <TableCell>{session.title}</TableCell>
                          <TableCell>{session.state ?? "–"}</TableCell>
                        </TableRow>
                      ))}
                      {!filteredSessions.length && (
                        <TableRow>
                          <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                            Keine aktiven Sitzungen.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="settings" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Settings2 className="h-4 w-4" /> Plex Einstellungen
              </CardTitle>
              <CardDescription>
                Verwalte URL, Token und Standardbibliothek für die Plex-Integration.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-6" onSubmit={handleSubmit}>
                <fieldset className="space-y-4" disabled={settingsLoading}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="plexBaseUrl">Plex Base URL</Label>
                      <Input
                        id="plexBaseUrl"
                        value={settings.plexBaseUrl}
                        onChange={(event) => handleSettingsChange("plexBaseUrl", event.target.value)}
                        placeholder="http://localhost:32400"
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="plexToken">Plex Token</Label>
                      <Input
                        id="plexToken"
                        value={settings.plexToken}
                        onChange={(event) => handleSettingsChange("plexToken", event.target.value)}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="plexLibrary">Standardbibliothek</Label>
                      <Input
                        id="plexLibrary"
                        value={settings.plexLibrary}
                        onChange={(event) => handleSettingsChange("plexLibrary", event.target.value)}
                        placeholder="Music"
                        required
                      />
                    </div>
                  </div>
                </fieldset>

                {settingsError ? (
                  <p className="text-sm text-destructive">{settingsError}</p>
                ) : null}

                <div className="flex items-center justify-end">
                  <Button type="submit" disabled={settingsSaving || settingsLoading}>
                    {settingsSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    Speichern
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default PlexPage;
