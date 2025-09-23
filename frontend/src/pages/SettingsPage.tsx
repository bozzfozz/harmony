import { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { fetchSettings, updateSetting } from '../lib/api';
import { useToast } from '../hooks/useToast';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';

const SETTINGS_SECTIONS = [
  {
    id: 'spotify',
    label: 'Spotify',
    fields: [
      { key: 'SPOTIFY_CLIENT_ID', label: 'Client ID' },
      { key: 'SPOTIFY_CLIENT_SECRET', label: 'Client Secret' },
      { key: 'SPOTIFY_REDIRECT_URI', label: 'Redirect URI' }
    ]
  },
  {
    id: 'plex',
    label: 'Plex',
    fields: [
      { key: 'PLEX_BASE_URL', label: 'Basis-URL' },
      { key: 'PLEX_TOKEN', label: 'Token' },
      { key: 'PLEX_LIBRARY', label: 'Bibliothek' }
    ]
  },
  {
    id: 'soulseek',
    label: 'Soulseek',
    fields: [
      { key: 'SLSKD_URL', label: 'slskd URL' },
      { key: 'SLSKD_API_KEY', label: 'API Key' }
    ]
  },
  {
    id: 'beets',
    label: 'Beets',
    fields: [
      { key: 'BEETS_LIBRARY_PATH', label: 'Library Pfad' },
      { key: 'BEETS_IMPORT_TARGET', label: 'Import Ziel' }
    ]
  }
] as const;

type FormValues = Record<string, string>;

const SettingsPage = () => {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Einstellungen konnten nicht geladen werden.',
        variant: 'destructive'
      })
  });

  const defaultValues = useMemo(() => {
    const settings = settingsQuery.data?.settings ?? {};
    const values: FormValues = {};
    SETTINGS_SECTIONS.forEach((section) => {
      section.fields.forEach((field) => {
        values[field.key] = settings[field.key] ?? '';
      });
    });
    return values;
  }, [settingsQuery.data?.settings]);

  const form = useForm<FormValues>({ defaultValues });

  useEffect(() => {
    form.reset(defaultValues);
  }, [defaultValues, form]);

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const settings = settingsQuery.data?.settings ?? {};
      const updates = Object.entries(values).filter(([key, value]) => (settings[key] ?? '') !== value);
      await Promise.all(
        updates.map(([key, value]) => updateSetting({ key, value: value.trim() === '' ? null : value }))
      );
    },
    onSuccess: () => {
      toast({ title: '✅ Einstellungen gespeichert' });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: () => toast({ title: '❌ Fehler beim Speichern', variant: 'destructive' })
  });

  if (settingsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <Tabs defaultValue="spotify">
      <TabsList className="grid grid-cols-2 gap-2 md:w-[480px] md:grid-cols-4">
        {SETTINGS_SECTIONS.map((section) => (
          <TabsTrigger key={section.id} value={section.id}>
            {section.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {SETTINGS_SECTIONS.map((section) => (
        <TabsContent key={section.id} value={section.id}>
          <form onSubmit={form.handleSubmit(mutation.mutate)}>
            <Card>
              <CardHeader>
                <CardTitle>{section.label} Einstellungen</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {section.fields.map((field) => (
                  <div className="grid gap-2" key={field.key}>
                    <Label htmlFor={field.key}>{field.label}</Label>
                    <Input id={field.key} {...form.register(field.key)} placeholder={`Wert für ${field.label}`} />
                  </div>
                ))}
              </CardContent>
              <CardFooter className="justify-end">
                <div className="flex gap-2">
                  <Button type="button" variant="ghost" onClick={() => form.reset(defaultValues)}>
                    Zurücksetzen
                  </Button>
                  <Button type="submit" disabled={mutation.isPending}>
                    {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    Speichern
                  </Button>
                </div>
              </CardFooter>
            </Card>
          </form>
        </TabsContent>
      ))}
    </Tabs>
  );
};

export default SettingsPage;
