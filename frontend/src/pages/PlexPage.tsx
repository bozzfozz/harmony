import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import {
  fetchPlexOverview,
  fetchSettings,
  SettingsData,
  updateSettings
} from '../lib/api';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { useToast } from '../hooks/useToast';

interface PlexSettingsForm {
  [key: string]: string;
}

const PlexPage = () => {
  const { toast } = useToast();
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load settings', variant: 'destructive' })
  });

  const overviewQuery = useQuery({
    queryKey: ['plex-overview'],
    queryFn: fetchPlexOverview,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load Plex overview', variant: 'destructive' })
  });

  const form = useForm<PlexSettingsForm>({ defaultValues: {} });

  useEffect(() => {
    if (settingsQuery.data?.plex) {
      form.reset(settingsQuery.data.plex);
    }
  }, [settingsQuery.data?.plex, form]);

  const mutation = useMutation({
    mutationFn: async (values: PlexSettingsForm) => {
      const payload: SettingsData = {
        spotify: settingsQuery.data?.spotify ?? {},
        plex: values,
        soulseek: settingsQuery.data?.soulseek ?? {},
        beets: settingsQuery.data?.beets ?? {}
      };
      return updateSettings(payload);
    },
    onSuccess: () => toast({ title: 'Plex settings saved' }),
    onError: () => toast({ title: 'Failed to save Plex settings', variant: 'destructive' })
  });

  const onSubmit = (values: PlexSettingsForm) => mutation.mutate(values);

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="space-y-6">
        {overviewQuery.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : null}
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Libraries</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.libraries ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Active Sessions</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.sessions ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Last Sync</CardTitle>
            </CardHeader>
            <CardContent className="text-lg font-medium">
              {overviewQuery.data?.lastSync ?? '–'}
            </CardContent>
          </Card>
        </div>
      </TabsContent>
      <TabsContent value="settings">
        <Card>
          <CardHeader>
            <CardTitle>Plex Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
              {Object.entries(settingsQuery.data?.plex ?? {}).map(([key]) => (
                <div className="grid gap-2" key={key}>
                  <Label htmlFor={key}>{key}</Label>
                  <Input id={key} {...form.register(key)} placeholder={`Enter ${key}`} />
                </div>
              ))}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => form.reset(settingsQuery.data?.plex ?? {})}>
                  Reset
                </Button>
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Save Changes
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
