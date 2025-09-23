import { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '../lib/query';
import { Loader2 } from 'lucide-react';
import { fetchSettings, updateSetting } from '../lib/api';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { useToast } from '../hooks/useToast';

const BEETS_FIELDS = [
  { key: 'BEETS_LIBRARY_PATH', label: 'Library Pfad' },
  { key: 'BEETS_IMPORT_TARGET', label: 'Import Ziel' }
] as const;

type BeetsSettingsForm = Record<(typeof BEETS_FIELDS)[number]['key'], string>;

const BeetsPage = () => {
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
    return BEETS_FIELDS.reduce<BeetsSettingsForm>((acc, field) => {
      acc[field.key] = settings[field.key] ?? '';
      return acc;
    }, {} as BeetsSettingsForm);
  }, [settingsQuery.data?.settings]);

  const form = useForm<BeetsSettingsForm>({ defaultValues });

  useEffect(() => {
    form.reset(defaultValues);
  }, [defaultValues, form]);

  const mutation = useMutation({
    mutationFn: async (values: BeetsSettingsForm) => {
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

  const handleSubmit = (values: BeetsSettingsForm) => mutation.mutate(values);

  const beetsEntries = useMemo(
    () =>
      Object.entries(settingsQuery.data?.settings ?? {})
        .filter(([key]) => key.startsWith('BEETS_'))
        .map(([key, value]) => ({ key, value })),
    [settingsQuery.data?.settings]
  );

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Übersicht</TabsTrigger>
        <TabsTrigger value="settings">Einstellungen</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        {settingsQuery.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : null}
        <Card>
          <CardHeader>
            <CardTitle>Beets Konfiguration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            {beetsEntries.length > 0 ? (
              beetsEntries.map((entry) => (
                <div className="flex justify-between" key={entry.key}>
                  <span>{entry.key}</span>
                  <span className="font-medium">{entry.value ?? '–'}</span>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">
                Keine Beets-spezifischen Einstellungen gespeichert. Nutzen Sie den Tab "Einstellungen", um Pfade anzulegen.
              </p>
            )}
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="settings">
        <Card>
          <CardHeader>
            <CardTitle>Beets Einstellungen</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={form.handleSubmit(handleSubmit)}>
              {BEETS_FIELDS.map((field) => (
                <div className="grid gap-2" key={field.key}>
                  <Label htmlFor={field.key}>{field.label}</Label>
                  <Input id={field.key} {...form.register(field.key)} placeholder={`Wert für ${field.label}`} />
                </div>
              ))}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => form.reset(defaultValues)}>
                  Zurücksetzen
                </Button>
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
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

export default BeetsPage;
