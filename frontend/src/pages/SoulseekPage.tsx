import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import {
  fetchSettings,
  fetchSoulseekOverview,
  SettingsData,
  updateSettings
} from '../lib/api';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { useToast } from '../hooks/useToast';

interface SoulseekSettingsForm {
  [key: string]: string;
}

const SoulseekPage = () => {
  const { toast } = useToast();
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load settings', variant: 'destructive' })
  });

  const overviewQuery = useQuery({
    queryKey: ['soulseek-overview'],
    queryFn: fetchSoulseekOverview,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load Soulseek overview', variant: 'destructive' })
  });

  const form = useForm<SoulseekSettingsForm>({ defaultValues: {} });

  useEffect(() => {
    if (settingsQuery.data?.soulseek) {
      form.reset(settingsQuery.data.soulseek);
    }
  }, [settingsQuery.data?.soulseek, form]);

  const mutation = useMutation({
    mutationFn: async (values: SoulseekSettingsForm) => {
      const payload: SettingsData = {
        spotify: settingsQuery.data?.spotify ?? {},
        plex: settingsQuery.data?.plex ?? {},
        soulseek: values,
        beets: settingsQuery.data?.beets ?? {}
      };
      return updateSettings(payload);
    },
    onSuccess: () => toast({ title: 'Soulseek settings saved' }),
    onError: () => toast({ title: 'Failed to save Soulseek settings', variant: 'destructive' })
  });

  const onSubmit = (values: SoulseekSettingsForm) => mutation.mutate(values);

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
              <CardTitle>Downloads</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.downloads ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Uploads</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.uploads ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Queue</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold">
              {overviewQuery.data?.queue ?? 0}
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
            <CardTitle>Soulseek Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
              {Object.entries(settingsQuery.data?.soulseek ?? {}).map(([key]) => (
                <div className="grid gap-2" key={key}>
                  <Label htmlFor={key}>{key}</Label>
                  <Input id={key} {...form.register(key)} placeholder={`Enter ${key}`} />
                </div>
              ))}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => form.reset(settingsQuery.data?.soulseek ?? {})}>
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

export default SoulseekPage;
