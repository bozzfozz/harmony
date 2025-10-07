import { FormEvent, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle, Loader2, Plus, RefreshCw, Search, XCircle } from 'lucide-react';

import {
  addArtistToWatchlist,
  listArtists,
  removeWatchlistEntry,
  updateWatchlistEntry,
  type ArtistSummary
} from '../../api/services/artists';
import type { ArtistPriority } from '../../api/types';
import { ApiError } from '../../api/client';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Input } from '../../components/ui/input';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from '../../components/ui/select';
import { Badge } from '../../components/ui/shadcn';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { useToast } from '../../hooks/useToast';
import useDebouncedValue from '../../hooks/useDebouncedValue';
import { useMutation, useQuery, useQueryClient } from '../../lib/query';

const HEALTH_FILTERS = [
  { value: 'all', label: 'Alle Zustände' },
  { value: 'ok', label: 'Gesund' },
  { value: 'warning', label: 'Warnung' },
  { value: 'error', label: 'Fehler' }
] as const;

const PRIORITY_OPTIONS: { value: ArtistPriority; label: string }[] = [
  { value: 'high', label: 'Hoch' },
  { value: 'medium', label: 'Mittel' },
  { value: 'low', label: 'Niedrig' }
];

const INTERVAL_OPTIONS = [1, 3, 7, 14, 30, 60] as const;

const getHealthIcon = (health?: string | null) => {
  if (health === 'ok' || health === 'healthy') {
    return <CheckCircle className="h-4 w-4 text-emerald-500" aria-hidden />;
  }
  if (health === 'warning' || health === 'degraded') {
    return <AlertCircle className="h-4 w-4 text-amber-500" aria-hidden />;
  }
  if (!health) {
    return <AlertCircle className="h-4 w-4 text-muted-foreground" aria-hidden />;
  }
  return <XCircle className="h-4 w-4 text-destructive" aria-hidden />;
};

const formatDate = (value?: string | null) => {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return new Intl.DateTimeFormat('de-DE', {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(date);
};

const ArtistsPage = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [priorityFilter, setPriorityFilter] = useState<'all' | ArtistPriority>('all');
  const [healthFilter, setHealthFilter] = useState<(typeof HEALTH_FILTERS)[number]['value']>('all');
  const [spotifyArtistId, setSpotifyArtistId] = useState('');
  const [artistName, setArtistName] = useState('');
  const [isRemoving, setIsRemoving] = useState<string | null>(null);

  const debouncedSearch = useDebouncedValue(search, 300);

  const queryKey = useMemo(
    () => ['artists', { search: debouncedSearch, priority: priorityFilter, health: healthFilter }],
    [debouncedSearch, priorityFilter, healthFilter]
  );

  const artistsQuery = useQuery({
    queryKey,
    queryFn: () =>
      listArtists({
        search: debouncedSearch || undefined,
        priority: priorityFilter,
        health: healthFilter,
        watchlistOnly: true
      }),
    onError: (error) => {
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Artists konnten nicht geladen werden',
        description: 'Bitte Verbindung prüfen und erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const addMutation = useMutation({
    mutationFn: addArtistToWatchlist,
    onSuccess: (artist) => {
      toast({
        title: 'Artist zur Watchlist hinzugefügt',
        description: artist?.name ? `${artist.name} wird künftig überwacht.` : undefined
      });
      setArtistName('');
      setSpotifyArtistId('');
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        if (error.status === 409) {
          toast({
            title: 'Artist bereits vorhanden',
            description: 'Dieser Artist ist schon Teil der Watchlist.',
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

  const priorityMutation = useMutation({
    mutationFn: async ({ artist, priority }: { artist: ArtistSummary; priority: ArtistPriority }) => {
      const watchlistId = artist.watchlist?.id ?? artist.id;
      await updateWatchlistEntry(watchlistId, { priority });
    },
    onSuccess: (_data, { priority }) => {
      toast({
        title: 'Priorität aktualisiert',
        description: `Neue Priorität: ${priority.toUpperCase()}`
      });
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Priorität konnte nicht aktualisiert werden',
        description: 'Bitte erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const intervalMutation = useMutation({
    mutationFn: async ({ artist, intervalDays }: { artist: ArtistSummary; intervalDays: number }) => {
      const watchlistId = artist.watchlist?.id ?? artist.id;
      await updateWatchlistEntry(watchlistId, { interval_days: intervalDays });
    },
    onSuccess: (_data, { intervalDays }) => {
      toast({
        title: 'Intervall angepasst',
        description: `Nächster Sync alle ${intervalDays} Tage.`
      });
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Intervall konnte nicht geändert werden',
        description: 'Bitte erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const removeMutation = useMutation({
    mutationFn: removeWatchlistEntry,
    onSuccess: () => {
      toast({
        title: 'Artist entfernt',
        description: 'Der Artist wird nicht mehr überwacht.'
      });
      setIsRemoving(null);
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => {
      setIsRemoving(null);
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Artist konnte nicht entfernt werden',
        description: 'Bitte erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const items = artistsQuery.data?.items ?? [];
  const isLoading = artistsQuery.isLoading;

  const handleAdd = (event: FormEvent<HTMLFormElement>) => {
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
    void addMutation.mutate({ spotify_artist_id: normalizedId, name: normalizedName });
  };

  const renderRows = () => {
    if (isLoading) {
      return (
        <TableRow>
          <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
            <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Lädt…</span>
          </TableCell>
        </TableRow>
      );
    }
    if (!items.length) {
      return (
        <TableRow>
          <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
            Keine Artists in der Watchlist gefunden.
          </TableCell>
        </TableRow>
      );
    }
    return items.map((artist) => {
      const watchlist = artist.watchlist;
      const intervalLabel = watchlist?.interval_days ? `${watchlist.interval_days} Tage` : 'Automatisch';
      const pendingMatches = typeof artist.matches_pending === 'number' ? artist.matches_pending : 0;
      const removalInProgress = isRemoving === (watchlist?.id ?? artist.id) && removeMutation.isPending;
      return (
        <TableRow key={artist.id}>
          <TableCell className="w-[22%] font-medium">
            <button
              type="button"
              className="text-left hover:underline"
              onClick={() => navigate(`/artists/${encodeURIComponent(artist.id)}`)}
            >
              {artist.name}
            </button>
            <div className="mt-1 text-xs text-muted-foreground">{artist.external_ids?.spotify ?? artist.id}</div>
          </TableCell>
          <TableCell className="w-[12%]">
            <div className="flex items-center gap-2">
              {getHealthIcon(artist.health_status)}
              <span className="text-sm capitalize">{artist.health_status ?? 'unbekannt'}</span>
            </div>
          </TableCell>
          <TableCell className="w-[18%]">
            <Select
              value={watchlist?.priority ?? 'medium'}
              onValueChange={(value) => {
                const next = value as ArtistPriority;
                void priorityMutation.mutate({ artist, priority: next });
              }}
            >
              <SelectTrigger className="h-9" aria-label={`Priorität für ${artist.name}`}>
                <SelectValue aria-label={watchlist?.priority ?? 'medium'} />
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  <SelectLabel>Priorität</SelectLabel>
                  {PRIORITY_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </TableCell>
          <TableCell className="w-[16%]">
            <Select
              value={String(watchlist?.interval_days ?? '')}
              onValueChange={(value) => {
                const parsed = Number(value);
                if (!Number.isNaN(parsed)) {
                  void intervalMutation.mutate({ artist, intervalDays: parsed });
                }
              }}
            >
              <SelectTrigger className="h-9" aria-label={`Sync-Intervall für ${artist.name}`}>
                <SelectValue placeholder="Automatisch" aria-label={intervalLabel} />
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  <SelectLabel>Sync-Intervall</SelectLabel>
                  {INTERVAL_OPTIONS.map((days) => (
                    <SelectItem key={days} value={String(days)}>
                      Alle {days} Tage
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </TableCell>
          <TableCell className="w-[14%]">
            <div className="space-y-1 text-sm">
              <div>
                <span className="font-medium">Zuletzt:</span> {formatDate(watchlist?.last_synced_at)}
              </div>
              <div className="text-xs text-muted-foreground">Nächster: {formatDate(watchlist?.next_sync_at)}</div>
            </div>
          </TableCell>
          <TableCell className="w-[18%] text-right">
            <div className="flex flex-col items-end gap-2">
              {pendingMatches > 0 ? <Badge variant="secondary">{pendingMatches} offene Matches</Badge> : null}
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => navigate(`/artists/${encodeURIComponent(artist.id)}`)}
                >
                  Details
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    const watchlistId = artist.watchlist?.id ?? artist.id;
                    if (!window.confirm(`Artist ${artist.name} wirklich entfernen?`)) {
                      return;
                    }
                    setIsRemoving(watchlistId);
                    void removeMutation.mutate(watchlistId);
                  }}
                  disabled={removeMutation.isPending && removalInProgress}
                >
                  {removalInProgress ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    'Entfernen'
                  )}
                </Button>
              </div>
            </div>
          </TableCell>
        </TableRow>
      );
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Artist Watchlist</h1>
          <p className="text-sm text-muted-foreground">Überblick über alle überwachten Artists und deren Sync-Status.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full min-w-[240px] lg:w-64">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Artist oder ID suchen"
              className="pl-9"
              aria-label="Watchlist durchsuchen"
            />
          </div>
          <Select value={priorityFilter} onValueChange={(value) => setPriorityFilter(value as typeof priorityFilter)}>
            <SelectTrigger className="w-[160px]" aria-label="Priorität filtern">
              <SelectValue placeholder="Priorität" />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectGroup>
                <SelectLabel>Priorität</SelectLabel>
                <SelectItem value="all">Alle Prioritäten</SelectItem>
                {PRIORITY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Select value={healthFilter} onValueChange={(value) => setHealthFilter(value as typeof healthFilter)}>
            <SelectTrigger className="w-[160px]" aria-label="Gesundheitsstatus filtern">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectGroup>
                <SelectLabel>Gesundheit</SelectLabel>
                {HEALTH_FILTERS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button type="button" variant="outline" onClick={() => queryClient.invalidateQueries({ queryKey })}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Neu laden
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card className="order-2 lg:order-1">
          <CardHeader>
            <CardTitle>Watchlist</CardTitle>
            <CardDescription>Bestehende Artists überwachen, Priorität und Sync-Intervalle anpassen.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-hidden rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Artist</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Priorität</TableHead>
                    <TableHead>Intervall</TableHead>
                    <TableHead>Letzte / nächste Syncs</TableHead>
                    <TableHead className="text-right">Aktionen</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>{renderRows()}</TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <Card className="order-1 lg:order-2">
          <CardHeader>
            <CardTitle>Artist hinzufügen</CardTitle>
            <CardDescription>Neue Artists überwachen und automatische Syncs aktivieren.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleAdd}>
              <div className="space-y-2">
                <label htmlFor="artist-name" className="text-sm font-medium">
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
              <div className="space-y-2">
                <label htmlFor="spotify-artist-id" className="text-sm font-medium">
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
              <div className="flex items-center justify-end">
                <Button type="submit" disabled={addMutation.isPending} className="inline-flex items-center gap-2">
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

      <Card>
        <CardHeader>
          <CardTitle>Direkt zu einem Artist</CardTitle>
          <CardDescription>Schnellnavigation zu einem bekannten Artist.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            {items.slice(0, 6).map((artist) => (
              <Badge key={artist.id} variant="outline" className="cursor-pointer" asChild>
                <Link to={`/artists/${encodeURIComponent(artist.id)}`}>{artist.name}</Link>
              </Badge>
            ))}
            {items.length === 0 ? (
              <span className="text-sm text-muted-foreground">
                Noch keine Artists verfügbar – zuerst zur Watchlist hinzufügen.
              </span>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default ArtistsPage;
