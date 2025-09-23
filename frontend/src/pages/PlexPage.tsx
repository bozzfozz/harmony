import { useMemo } from 'react';
import { Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '../components/ui/table';
import { useToast } from '../hooks/useToast';
import { useQuery } from '../lib/query';
import { fetchPlexLibraries, fetchPlexStatus } from '../lib/api';
import useServiceSettingsForm from '../hooks/useServiceSettingsForm';

const settingsFields = [
  { key: 'PLEX_BASE_URL', label: 'Base URL', placeholder: 'https://plex.example.com' },
  { key: 'PLEX_TOKEN', label: 'Access token', placeholder: 'Plex token' },
  { key: 'PLEX_LIBRARY', label: 'Library name', placeholder: 'Music' }
] as const;

const PlexPage = () => {
  const { toast } = useToast();

  const statusQuery = useQuery({
    queryKey: ['plex-status'],
    queryFn: fetchPlexStatus,
    refetchInterval: 45000,
    onError: () =>
      toast({
        title: 'Failed to load Plex status',
        description: 'Could not connect to the Plex backend.',
        variant: 'destructive'
      })
  });

  const librariesQuery = useQuery({
    queryKey: ['plex-libraries'],
    queryFn: fetchPlexLibraries,
    refetchInterval: 60000,
    onError: () =>
      toast({
        title: 'Failed to load Plex libraries',
        description: 'Library sections could not be fetched.',
        variant: 'destructive'
      })
  });

  const { form, onSubmit, handleReset, isSaving, isLoading } = useServiceSettingsForm({
    fields: settingsFields,
    loadErrorDescription: 'Plex settings could not be loaded.',
    successTitle: 'Plex settings saved',
    errorTitle: 'Failed to save Plex settings'
  });

  const sessionCount = useMemo(() => {
    const sessions = statusQuery.data?.sessions;
    if (Array.isArray(sessions)) {
      return sessions.length;
    }
    if (sessions && typeof sessions === 'object') {
      return Object.keys(sessions).length;
    }
    return 0;
  }, [statusQuery.data?.sessions]);

  const libraryStats = useMemo(() => {
    const entries = Object.entries((statusQuery.data?.library ?? {}) as Record<string, unknown>);
    if (entries.length === 0) {
      return [] as Array<[string, unknown]>;
    }
    return entries;
  }, [statusQuery.data?.library]);

  const libraries = useMemo(() => {
    const raw = librariesQuery.data as Record<string, unknown> | undefined;
    if (!raw) {
      return [] as Array<Record<string, unknown>>;
    }
    const container = (raw.MediaContainer ?? raw) as Record<string, unknown>;
    const directories = container.Directory ?? container.directories;
    if (Array.isArray(directories)) {
      return directories as Array<Record<string, unknown>>;
    }
    if (directories) {
      return [directories as Record<string, unknown>];
    }
    return [] as Array<Record<string, unknown>>;
  }, [librariesQuery.data]);

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Connection status</CardTitle>
            </CardHeader>
            <CardContent>
              {statusQuery.isLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <div className="space-y-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span>Status</span>
                    <span className="font-medium capitalize">
                      {statusQuery.data?.status ?? 'unknown'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Sessions</span>
                    <span className="font-medium">{sessionCount}</span>
                  </div>
                  {libraryStats.length > 0 ? (
                    <div className="space-y-1 text-xs text-muted-foreground">
                      <p className="font-semibold text-foreground">Library statistics</p>
                      {libraryStats.map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between">
                          <span className="capitalize">{key.replace(/_/g, ' ')}</span>
                          <span className="font-medium text-foreground">{String(value)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      No statistics returned by the Plex server.
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Libraries</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              {librariesQuery.isLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Agent</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {libraries.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                          No library sections reported yet.
                        </TableCell>
                      </TableRow>
                    ) : (
                      libraries.map((library) => (
                        <TableRow key={String(library.key ?? library.uuid ?? library.title)}>
                          <TableCell className="font-medium">
                            {String(library.title ?? 'Unknown')}
                          </TableCell>
                          <TableCell>{String(library.type ?? '—')}</TableCell>
                          <TableCell>{String(library.agent ?? '—')}</TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </TabsContent>
      <TabsContent value="settings">
        <Card>
          <CardHeader>
            <CardTitle>Plex connection</CardTitle>
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

export default PlexPage;
