import { useQuery } from '../lib/query';
import { Loader2 } from 'lucide-react';
import { fetchPlexStatus } from '../lib/api';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { useToast } from '../hooks/useToast';
import useServiceSettingsForm from '../hooks/useServiceSettingsForm';

const PLEX_FIELDS = [
  { key: 'PLEX_BASE_URL', label: 'Basis-URL' },
  { key: 'PLEX_TOKEN', label: 'Token' },
  { key: 'PLEX_LIBRARY', label: 'Bibliothek' }
] as const;

const PlexPage = () => {
  const { toast } = useToast();

  const statusQuery = useQuery({
    queryKey: ['plex-status'],
    queryFn: fetchPlexStatus,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Plex-Status konnte nicht geladen werden.',
        variant: 'destructive'
      })
  });

  const { form, onSubmit: handleSettingsSubmit, handleReset: handleSettingsReset, isSaving: isSavingSettings } =
    useServiceSettingsForm({ fields: PLEX_FIELDS });

  const libraryStats = statusQuery.data?.library ?? {};
  const sessionsContainer = (statusQuery.data?.sessions as Record<string, unknown> | undefined)?.MediaContainer as
    | Record<string, unknown>
    | undefined;
  const sessions = Array.isArray(sessionsContainer?.Metadata)
    ? (sessionsContainer?.Metadata as Array<Record<string, unknown>>)
    : [];

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Übersicht</TabsTrigger>
        <TabsTrigger value="settings">Einstellungen</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="space-y-6">
        {statusQuery.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : null}
        <div className="grid gap-6 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Verbindung</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <div className="flex justify-between">
                <span>Status</span>
                <span className="font-medium">{statusQuery.data?.status ?? 'unbekannt'}</span>
              </div>
              <div className="flex justify-between">
                <span>Aktive Sessions</span>
                <span>{sessions.length}</span>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Bibliothek</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <div className="flex justify-between">
                <span>Artists</span>
                <span>{libraryStats.artists ?? 0}</span>
              </div>
              <div className="flex justify-between">
                <span>Alben</span>
                <span>{libraryStats.albums ?? 0}</span>
              </div>
              <div className="flex justify-between">
                <span>Tracks</span>
                <span>{libraryStats.tracks ?? 0}</span>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Weitere Kennzahlen</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              {Object.entries(libraryStats)
                .filter(([key]) => !['artists', 'albums', 'tracks'].includes(key))
                .map(([key, value]) => (
                  <div className="flex justify-between" key={key}>
                    <span>{key}</span>
                    <span>{value as number}</span>
                  </div>
                ))}
              {Object.keys(libraryStats).length === 0 ? (
                <p className="text-sm text-muted-foreground">Keine Statistiken vorhanden.</p>
              ) : null}
            </CardContent>
          </Card>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Aktive Sessions</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Benutzer</TableHead>
                  <TableHead>Titel</TableHead>
                  <TableHead className="text-right">Typ</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session, index) => (
                  <TableRow key={String(session.sessionKey ?? index)}>
                    <TableCell className="font-medium">
                      {String(session.user?.title ?? session.User?.title ?? 'Unbekannt')}
                    </TableCell>
                    <TableCell>
                      {String(session.title ?? session.Metadata?.title ?? 'Unbekannter Titel')}
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {String(session.type ?? session.Metadata?.type ?? 'n/a')}
                    </TableCell>
                  </TableRow>
                ))}
                {sessions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                      Keine aktiven Sessions.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="settings">
        <Card>
          <CardHeader>
            <CardTitle>Plex Konfiguration</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSettingsSubmit}>
              {PLEX_FIELDS.map((field) => (
                <div className="grid gap-2" key={field.key}>
                  <Label htmlFor={field.key}>{field.label}</Label>
                  <Input id={field.key} {...form.register(field.key)} placeholder={`Wert für ${field.label}`} />
                </div>
              ))}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={handleSettingsReset}>
                  Zurücksetzen
                </Button>
                <Button type="submit" disabled={isSavingSettings}>
                  {isSavingSettings ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
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

export default PlexPage;
