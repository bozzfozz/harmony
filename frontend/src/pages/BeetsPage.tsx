import { Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { useQuery } from '../lib/query';
import { fetchBeetsOverview } from '../lib/api';
import useServiceSettingsForm from '../hooks/useServiceSettingsForm';

const formatDateTime = (value: string) => {
  if (!value) {
    return 'Never';
  }
  try {
    return new Intl.DateTimeFormat('en', {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date(value));
  } catch (error) {
    return value;
  }
};

const settingsFields = [
  { key: 'beets.host', label: 'Host', placeholder: 'localhost' },
  { key: 'beets.port', label: 'Port', placeholder: '8337' },
  { key: 'beets.apiKey', label: 'API key', placeholder: 'Optional API key' }
] as const;

const BeetsPage = () => {
  const overviewQuery = useQuery({
    queryKey: ['beets-overview'],
    queryFn: fetchBeetsOverview,
    refetchInterval: 60000
  });

  const { form, onSubmit, handleReset, isSaving, isLoading } = useServiceSettingsForm({
    fields: settingsFields,
    loadErrorDescription: 'Beets settings could not be loaded.',
    successTitle: 'Beets settings saved',
    errorTitle: 'Failed to save Beets settings'
  });

  const overview = overviewQuery.data ?? {
    albums: 0,
    artists: 0,
    tracks: 0,
    lastSync: ''
  };

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <Card>
          <CardHeader>
            <CardTitle>Beets library</CardTitle>
          </CardHeader>
          <CardContent>
            {overviewQuery.isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Albums</p>
                  <p className="mt-2 text-2xl font-semibold">{overview.albums}</p>
                </div>
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Artists</p>
                  <p className="mt-2 text-2xl font-semibold">{overview.artists}</p>
                </div>
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Tracks</p>
                  <p className="mt-2 text-2xl font-semibold">{overview.tracks}</p>
                </div>
                <div className="rounded-lg border bg-card p-4">
                  <p className="text-sm text-muted-foreground">Last import</p>
                  <p className="mt-2 text-base font-semibold">{formatDateTime(overview.lastSync)}</p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="settings">
        <Card>
          <CardHeader>
            <CardTitle>Beets connection</CardTitle>
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

export default BeetsPage;
