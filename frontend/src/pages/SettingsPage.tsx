import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { fetchSettings, SettingsData, updateSettings } from '../lib/api';
import { useToast } from '../hooks/useToast';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';

const SettingsPage = () => {
  const { toast } = useToast();
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () => toast({ title: 'Unable to load settings', variant: 'destructive' })
  });

  const form = useForm<SettingsData>({
    defaultValues: {
      spotify: {},
      plex: {},
      soulseek: {},
      beets: {}
    }
  });

  useEffect(() => {
    if (settingsQuery.data) {
      form.reset(settingsQuery.data);
    }
  }, [settingsQuery.data, form]);

  const mutation = useMutation({
    mutationFn: (values: SettingsData) => updateSettings(values),
    onSuccess: () => toast({ title: 'Settings updated successfully' }),
    onError: () => toast({ title: 'Failed to update settings', variant: 'destructive' })
  });

  const onSubmit = (values: SettingsData) => mutation.mutate(values);

  if (settingsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const renderSettingsFields = (section: keyof SettingsData) => (
    <div className="space-y-4">
      {Object.entries(form.getValues(section) ?? {}).map(([key]) => (
        <div className="grid gap-2" key={`${section}-${key}`}>
          <Label htmlFor={`${section}.${key}`}>{key}</Label>
          <Input id={`${section}.${key}`} {...form.register(`${section}.${key}`)} placeholder={`Enter ${key}`} />
        </div>
      ))}
    </div>
  );

  return (
    <Tabs defaultValue="spotify">
      <TabsList className="grid grid-cols-2 gap-2 md:w-[480px] md:grid-cols-4">
        <TabsTrigger value="spotify">Spotify</TabsTrigger>
        <TabsTrigger value="plex">Plex</TabsTrigger>
        <TabsTrigger value="soulseek">Soulseek</TabsTrigger>
        <TabsTrigger value="beets">Beets</TabsTrigger>
      </TabsList>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <TabsContent value="spotify">
          <Card>
            <CardHeader>
              <CardTitle>Spotify Settings</CardTitle>
            </CardHeader>
            <CardContent>{renderSettingsFields('spotify')}</CardContent>
            <CardFooter className="justify-end">
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Save Changes
              </Button>
            </CardFooter>
          </Card>
        </TabsContent>
        <TabsContent value="plex">
          <Card>
            <CardHeader>
              <CardTitle>Plex Settings</CardTitle>
            </CardHeader>
            <CardContent>{renderSettingsFields('plex')}</CardContent>
            <CardFooter className="justify-end">
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Save Changes
              </Button>
            </CardFooter>
          </Card>
        </TabsContent>
        <TabsContent value="soulseek">
          <Card>
            <CardHeader>
              <CardTitle>Soulseek Settings</CardTitle>
            </CardHeader>
            <CardContent>{renderSettingsFields('soulseek')}</CardContent>
            <CardFooter className="justify-end">
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Save Changes
              </Button>
            </CardFooter>
          </Card>
        </TabsContent>
        <TabsContent value="beets">
          <Card>
            <CardHeader>
              <CardTitle>Beets Settings</CardTitle>
            </CardHeader>
            <CardContent>{renderSettingsFields('beets')}</CardContent>
            <CardFooter className="justify-end">
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Save Changes
              </Button>
            </CardFooter>
          </Card>
        </TabsContent>
      </form>
    </Tabs>
  );
};

export default SettingsPage;
