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
import { fetchSoulseekDownloads, fetchSoulseekStatus } from '../lib/api';
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
  { key: 'SLSKD_URL', label: 'Daemon URL', placeholder: 'http://localhost:5030' },
  { key: 'SLSKD_API_KEY', label: 'API key', placeholder: 'Optional API key' }
] as const;

const SoulseekPage = () => {
  const { toast } = useToast();

  const statusQuery = useQuery({
    queryKey: ['soulseek-status'],
    queryFn: fetchSoulseekStatus,
    refetchInterval: 45000,
    onError: () =>
      toast({
        title: 'Failed to load Soulseek status',
        description: 'Soulseek daemon did not respond.',
        variant: 'destructive'
      })
  });

  const downloadsQuery = useQuery({
    queryKey: ['soulseek-downloads'],
    queryFn: fetchSoulseekDownloads,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: 'Failed to load downloads',
        description: 'Queued downloads could not be retrieved.',
        variant: 'destructive'
      })
  });

  const { form, onSubmit, handleReset, isSaving, isLoading } = useServiceSettingsForm({
    fields: settingsFields,
    loadErrorDescription: 'Soulseek settings could not be loaded.',
    successTitle: 'Soulseek settings saved',
    errorTitle: 'Failed to save Soulseek settings'
  });

  const downloads = downloadsQuery.data ?? [];
  const status = statusQuery.data?.status ?? 'unknown';

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
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span>Status</span>
                    <span className="font-medium capitalize">{status}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    The Soulseek daemon is queried directly via the backend.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Recent downloads</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              {downloadsQuery.isLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Filename</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Progress</TableHead>
                      <TableHead>Updated</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {downloads.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                          No downloads have been queued yet.
                        </TableCell>
                      </TableRow>
                    ) : (
                      downloads.map((download) => (
                        <TableRow key={download.id}>
                          <TableCell className="font-medium">{download.filename}</TableCell>
                          <TableCell className="capitalize">{download.state}</TableCell>
                          <TableCell>{download.progress.toFixed(1)}%</TableCell>
                          <TableCell>{formatDateTime(download.updated_at)}</TableCell>
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
            <CardTitle>Soulseek credentials</CardTitle>
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

export default SoulseekPage;
