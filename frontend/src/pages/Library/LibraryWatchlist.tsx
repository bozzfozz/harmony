import { FormEvent, useMemo, useState } from 'react';
import { Loader2, Plus, Trash2 } from 'lucide-react';

import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input
} from '../../components/ui/shadcn';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { useToast } from '../../hooks/useToast';
import {
  ApiError,
  WatchlistArtistEntry,
  addWatchlistArtist,
  getWatchlist,
  removeWatchlistArtist
} from '../../lib/api';
import { useMutation, useQuery } from '../../lib/query';

const LibraryWatchlist = () => {
  const { toast } = useToast();
  const [spotifyArtistId, setSpotifyArtistId] = useState('');
  const [artistName, setArtistName] = useState('');
  const [removalId, setRemovalId] = useState<number | null>(null);

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat('de-DE', {
        dateStyle: 'medium',
        timeStyle: 'short'
      }),
    []
  );

  const watchlistQuery = useQuery<WatchlistArtistEntry[]>({
    queryKey: ['watchlist-artists'],
    queryFn: getWatchlist,
    onError: (error) => {
      if (error instanceof ApiError) {
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      toast({
        title: 'Watchlist konnte nicht geladen werden',
        description: 'Bitte Backend-Verbindung prüfen.',
        variant: 'destructive'
      });
    }
  });

  const addMutation = useMutation({
    mutationFn: addWatchlistArtist,
    onSuccess: (entry) => {
      toast({
        title: 'Artist zur Watchlist hinzugefügt',
        description: `${entry.name} wird künftig automatisch überwacht.`
      });
      setSpotifyArtistId('');
      setArtistName('');
      void watchlistQuery.refetch();
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        if (error.status === 409) {
          toast({
            title: 'Artist bereits vorhanden',
            description: 'Dieser Artist ist schon in der Watchlist.',
            variant: 'destructive'
          });
          return;
        }
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      toast({
        title: 'Watchlist konnte nicht aktualisiert werden',
        description: 'Bitte Eingaben prüfen und erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const removeMutation = useMutation<number | string, void>({
    mutationFn: removeWatchlistArtist,
    onSuccess: () => {
      toast({
        title: 'Watchlist-Eintrag entfernt',
        description: 'Der Artist wird nicht mehr automatisch überwacht.'
      });
      setRemovalId(null);
      void watchlistQuery.refetch();
    },
    onError: (error) => {
      setRemovalId(null);
      if (error instanceof ApiError) {
        if (error.status === 404) {
          toast({
            title: 'Artist nicht gefunden',
            description: 'Der Eintrag wurde bereits entfernt.',
            variant: 'destructive'
          });
          return;
        }
        if (error.handled) {
          return;
        }
        error.markHandled();
      }
      toast({
        title: 'Watchlist konnte nicht aktualisiert werden',
        description: 'Bitte versuchen Sie es erneut.',
        variant: 'destructive'
      });
    }
  });

  const items = watchlistQuery.data ?? [];
  const isLoading = watchlistQuery.isLoading;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedId = spotifyArtistId.trim();
    const normalizedName = artistName.trim();
    if (!normalizedId || !normalizedName) {
      toast({
        title: 'Bitte alle Felder ausfüllen',
        description: 'Spotify-Artist-ID und Name werden benötigt.',
        variant: 'destructive'
      });
      return;
    }
    void addMutation.mutate({
      spotify_artist_id: normalizedId,
      name: normalizedName
    });
  };

  const renderTableBody = () => {
    if (isLoading) {
      return (
        <TableRow>
          <TableCell colSpan={4} className="py-12 text-center text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Lädt Watchlist…
            </span>
          </TableCell>
        </TableRow>
      );
    }

    if (!items.length) {
      return (
        <TableRow>
          <TableCell colSpan={4} className="py-12 text-center text-muted-foreground">
            Noch keine Artists in der Watchlist.
          </TableCell>
        </TableRow>
      );
    }

    return items.map((entry) => {
      const lastCheckedLabel = entry.last_checked
        ? dateFormatter.format(new Date(entry.last_checked))
        : '—';
      const createdAtLabel = entry.created_at
        ? dateFormatter.format(new Date(entry.created_at))
        : '—';
      const isRemoving = removalId === entry.id && removeMutation.isPending;
      return (
        <TableRow key={entry.id}>
          <TableCell className="font-medium">{entry.name}</TableCell>
          <TableCell className="text-sm text-muted-foreground">{entry.spotify_artist_id}</TableCell>
          <TableCell className="text-sm text-muted-foreground">{lastCheckedLabel}</TableCell>
          <TableCell className="text-right">
            <div className="flex items-center justify-end gap-2">
              <span className="text-xs text-muted-foreground">{createdAtLabel}</span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setRemovalId(entry.id);
                  void removeMutation.mutate(entry.id);
                }}
                disabled={removeMutation.isPending}
              >
                {isRemoving ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <span className="inline-flex items-center gap-2">
                    <Trash2 className="h-4 w-4" aria-hidden /> Entfernen
                  </span>
                )}
              </Button>
            </div>
          </TableCell>
        </TableRow>
      );
    });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Card className="order-2 lg:order-1">
        <CardHeader>
          <CardTitle>Watchlist</CardTitle>
          <CardDescription>Alle Artists, die automatisch auf neue Releases geprüft werden.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Artist</TableHead>
                  <TableHead>Spotify-ID</TableHead>
                  <TableHead>Zuletzt geprüft</TableHead>
                  <TableHead className="text-right">Aktionen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>{renderTableBody()}</TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      <Card className="order-1 lg:order-2">
        <CardHeader>
          <CardTitle>Artist hinzufügen</CardTitle>
          <CardDescription>Neue Artists überwachen und automatische Downloads aktivieren.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="spotify-artist-id">
                Spotify-Artist-ID
              </label>
              <Input
                id="spotify-artist-id"
                value={spotifyArtistId}
                onChange={(event) => setSpotifyArtistId(event.target.value)}
                placeholder="z. B. 4tZwfgrHOc3mvqYlEYSvVi"
                aria-required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="artist-name">
                Name
              </label>
              <Input
                id="artist-name"
                value={artistName}
                onChange={(event) => setArtistName(event.target.value)}
                placeholder="z. B. Moderat"
                aria-required
              />
            </div>
            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                type="submit"
                disabled={addMutation.isPending}
                className="inline-flex items-center gap-2"
              >
                {addMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Hinzufügen…
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4" aria-hidden /> Zur Watchlist hinzufügen
                  </>
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default LibraryWatchlist;
