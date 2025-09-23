import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Search } from 'lucide-react';
import {
  fetchSettings,
  fetchSoulseekDownloads,
  fetchSoulseekStatus,
  searchSoulseek,
  updateSetting,
  SoulseekDownloadEntry
} from '../lib/api';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { useToast } from '../hooks/useToast';

const SOULSEEK_FIELDS = [
  { key: 'SLSKD_URL', label: 'slskd URL' },
  { key: 'SLSKD_API_KEY', label: 'API Key' }
] as const;

type SoulseekSettingsForm = Record<(typeof SOULSEEK_FIELDS)[number]['key'], string>;

const SoulseekPage = () => {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [hasSearched, setHasSearched] = useState(false);

  const statusQuery = useQuery({
    queryKey: ['soulseek-status'],
    queryFn: fetchSoulseekStatus,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Soulseek-Status konnte nicht geladen werden.',
        variant: 'destructive'
      })
  });

  const downloadsQuery = useQuery({
    queryKey: ['soulseek-downloads'],
    queryFn: fetchSoulseekDownloads,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Downloads konnten nicht geladen werden.',
        variant: 'destructive'
      })
  });

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

  const searchMutation = useMutation({
    mutationFn: (term: string) => searchSoulseek(term),
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Soulseek-Suche fehlgeschlagen.',
        variant: 'destructive'
      })
  });

  const defaultValues = useMemo(() => {
    const settings = settingsQuery.data?.settings ?? {};
    return SOULSEEK_FIELDS.reduce<SoulseekSettingsForm>((acc, field) => {
      acc[field.key] = settings[field.key] ?? '';
      return acc;
    }, {} as SoulseekSettingsForm);
  }, [settingsQuery.data?.settings]);

  const form = useForm<SoulseekSettingsForm>({ defaultValues });

  useEffect(() => {
    form.reset(defaultValues);
  }, [defaultValues, form]);

  const mutation = useMutation({
    mutationFn: async (values: SoulseekSettingsForm) => {
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

  const handleSubmit = (values: SoulseekSettingsForm) => mutation.mutate(values);

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = searchTerm.trim();
    if (!trimmed) {
      return;
    }
    setHasSearched(true);
    searchMutation.mutate(trimmed);
  };

  const downloads: SoulseekDownloadEntry[] = downloadsQuery.data?.downloads ?? [];

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Übersicht</TabsTrigger>
        <TabsTrigger value="settings">Einstellungen</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="space-y-6">
        {downloadsQuery.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : null}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Status & Warteschlange</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <div className="flex justify-between">
                <span>Status</span>
                <span className="font-medium">{statusQuery.data?.status ?? 'unbekannt'}</span>
              </div>
              <div className="flex justify-between">
                <span>Downloads</span>
                <span>{downloads.length}</span>
              </div>
              <div className="flex justify-between">
                <span>Aktiv</span>
                <span>{downloads.filter((download) => download.state === 'running').length}</span>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Soulseek Suche</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <form className="flex items-center gap-2" onSubmit={handleSearch}>
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Dateien oder Nutzer suchen"
                    className="pl-9"
                  />
                </div>
                <Button type="submit" disabled={searchMutation.isPending}>
                  {searchMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Suchen
                </Button>
              </form>
              <div className="space-y-2">
                {hasSearched && (searchMutation.data?.results?.length ?? 0) === 0 ? (
                  <p className="text-sm text-muted-foreground">Keine Treffer gefunden.</p>
                ) : null}
                <ul className="space-y-2">
                  {(searchMutation.data?.results ?? []).map((result, index) => {
                    const entry = result as Record<string, unknown>;
                    return (
                      <li key={index} className="rounded-lg border bg-card p-3">
                        <p className="text-sm font-semibold">
                          {String(entry.filename ?? entry.name ?? entry.title ?? 'Unbekannt')}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {entry.username ? `User: ${String(entry.username)}` : 'Quelle unbekannt'}
                        </p>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </CardContent>
          </Card>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Downloads</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Datei</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Fortschritt</TableHead>
                  <TableHead className="text-right">Aktualisiert</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {downloads.map((download) => (
                  <TableRow key={download.id}>
                    <TableCell className="font-medium">{download.filename}</TableCell>
                    <TableCell>{download.state}</TableCell>
                    <TableCell className="min-w-[160px]">
                      <Progress value={Math.min(100, Math.max(0, download.progress))} />
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {new Date(download.updated_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
                {downloads.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                      Keine Downloads vorhanden.
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
            <CardTitle>Soulseek Konfiguration</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={form.handleSubmit(handleSubmit)}>
              {SOULSEEK_FIELDS.map((field) => (
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

export default SoulseekPage;
