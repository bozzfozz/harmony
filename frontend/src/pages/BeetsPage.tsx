import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import {
  fetchBeetsOverview,
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

interface BeetsSettingsForm {
  [key: string]: string;
}

const BeetsPage = () => {
  const { toast } = useToast();
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load settings', variant: 'destructive' })
  });

  const overviewQuery = useQuery({
    queryKey: ['beets-overview'],
    queryFn: fetchBeetsOverview,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load Beets overview', variant: 'destructive' })
  });

  const form = useForm<BeetsSettingsForm>({ defaultValues: {} });

  useEffect(() => {
    if (settingsQuery.data?.beets) {
      form.reset(settingsQuery.data.beets);
    }
  }, [settingsQuery.data?.beets, form]);

  const mutation = useMutation({
    mutationFn: async (values: BeetsSettingsForm) => {
      const payload: SettingsData = {
        spotify: settingsQuery.data?.spotify ?? {},
        plex: settingsQuery.data?.plex ?? {},
        soulseek: settingsQuery.data?.soulseek ?? {},
        beets: values
      };
      return updateSettings(payload);
    },
    onSuccess: () => toast({ title: 'Beets settings saved' }),
    onError: () => toast({ title: 'Failed to save Beets settings', variant: 'destructive' })
  });

  const onSubmit = (values: BeetsSettingsForm) => mutation.mutate(values);

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
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          <Card>
            <CardHeader>
              <CardTitle>Albums</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.albums ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Artists</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.artists ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Tracks</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.tracks ?? 0}
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
            <CardTitle>Beets Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
              {Object.entries(settingsQuery.data?.beets ?? {}).map(([key]) => (
                <div className="grid gap-2" key={key}>
                  <Label htmlFor={key}>{key}</Label>
                  <Input id={key} {...form.register(key)} placeholder={`Enter ${key}`} />
                </div>
              ))}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => form.reset(settingsQuery.data?.beets ?? {})}>
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

export default BeetsPage;
