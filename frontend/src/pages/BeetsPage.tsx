import { FormEvent, useMemo, useState } from 'react';
import { Loader2, RefreshCcw } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import { Switch } from '../components/ui/switch';
import { useToast } from '../hooks/useToast';
import { useMutation, useQuery, useQueryClient } from '../lib/query';
import { fetchBeetsStats, runBeetsImport } from '../lib/api';

const BeetsPage = () => {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [importPath, setImportPath] = useState('');
  const [quiet, setQuiet] = useState(true);
  const [autotag, setAutotag] = useState(true);

  const statsQuery = useQuery({
    queryKey: ['beets-stats'],
    queryFn: fetchBeetsStats,
    refetchInterval: 60000,
    onError: () =>
      toast({
        title: 'Failed to load Beets statistics',
        description: 'Make sure the Beets integration is configured correctly.',
        variant: 'destructive'
      })
  });

  const importMutation = useMutation({
    mutationFn: runBeetsImport,
    onSuccess: (data, payload) => {
      toast({ title: 'Import started', description: data.message });
      queryClient.invalidateQueries({ queryKey: ['beets-stats'] });
      setImportPath('');
    },
    onError: () =>
      toast({
        title: 'Import failed',
        description: 'Beets could not start the import job.',
        variant: 'destructive'
      })
  });

  const statsEntries = useMemo(() => {
    const stats = statsQuery.data?.stats ?? {};
    return Object.entries(stats);
  }, [statsQuery.data?.stats]);

  const handleImport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = importPath.trim();
    if (!trimmed) {
      toast({
        title: 'Path required',
        description: 'Please provide the path to the music you want to import.',
        variant: 'destructive'
      });
      return;
    }
    await importMutation.mutate({ path: trimmed, quiet, autotag });
  };

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Library</TabsTrigger>
        <TabsTrigger value="import">Import</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Beets statistics</CardTitle>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => statsQuery.refetch()}
                disabled={statsQuery.isLoading}
                className="inline-flex items-center gap-1"
              >
                <RefreshCcw className="h-4 w-4" /> Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {statsQuery.isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-3">
                {statsEntries.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No statistics available from the Beets server yet.
                  </p>
                ) : (
                  statsEntries.map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between text-sm">
                      <span className="capitalize text-muted-foreground">{key.replace(/_/g, ' ')}</span>
                      <span className="font-semibold">{value}</span>
                    </div>
                  ))
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="import">
        <Card>
          <CardHeader>
            <CardTitle>Import music</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleImport} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="beets-path">Path to import</Label>
                <Input
                  id="beets-path"
                  placeholder="/music/new"
                  value={importPath}
                  onChange={(event) => setImportPath(event.target.value)}
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex items-center justify-between gap-4 rounded-md border p-3">
                  <span className="text-sm">Quiet mode</span>
                  <Switch checked={quiet} onCheckedChange={(value) => setQuiet(Boolean(value))} />
                </label>
                <label className="flex items-center justify-between gap-4 rounded-md border p-3">
                  <span className="text-sm">Autotag</span>
                  <Switch
                    checked={autotag}
                    onCheckedChange={(value) => setAutotag(Boolean(value))}
                  />
                </label>
              </div>
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={importMutation.isPending}>
                  {importMutation.isPending ? (
                    <span className="inline-flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" /> Starting import…
                    </span>
                  ) : (
                    'Start import'
                  )}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setImportPath('');
                    setQuiet(true);
                    setAutotag(true);
                  }}
                  disabled={importMutation.isPending}
                >
                  Reset
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
