import { useQuery } from '../lib/query';
import { Loader2 } from 'lucide-react';
import { fetchSoulseekDownloads, SoulseekDownloadEntry } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';
import { useToast } from '../hooks/useToast';

const MatchingPage = () => {
  const { toast } = useToast();
  const downloadsQuery = useQuery({
    queryKey: ['soulseek-downloads'],
    queryFn: fetchSoulseekDownloads,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: 'Matching-Jobs konnten nicht geladen werden.',
        variant: 'destructive'
      })
  });

  const downloads: SoulseekDownloadEntry[] = downloadsQuery.data?.downloads ?? [];

  return (
    <div className="space-y-6">
      {downloadsQuery.isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>Matching Warteschlange</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            Die Matching-Engine verarbeitet Soulseek-Downloads und weist sie Spotify-Objekten zu. Die folgende Tabelle zeigt den
            aktuellen Stand der Jobs aus der Datenbank.
          </p>
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
                    Keine Matching-Jobs vorhanden.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

export default MatchingPage;
