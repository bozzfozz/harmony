import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { ArrowLeft, Check, Loader2, RefreshCw, ShieldAlert, ShieldCheck, X } from 'lucide-react';

import {
  enqueueArtistResync,
  getArtistDetail,
  invalidateArtistCache,
  updateArtistMatchStatus,
  type ArtistMatch
} from '../../api/services/artists';
import type { ArtistDetailResponse, ArtistMatchStatus, ArtistRelease } from '../../api/types';
import { ApiError } from '../../api/client';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/shadcn';
import { ScrollArea } from '../../components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/shadcn';
import { useToast } from '../../hooks/useToast';
import { useMutation, useQuery, useQueryClient } from '../../lib/query';

const MATCH_STATUS_ORDER: ArtistMatchStatus[] = ['pending', 'accepted', 'rejected'];

const formatDateTime = (value?: string | null, fallback = '—') => {
  if (!value) {
    return fallback;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }
  return new Intl.DateTimeFormat('de-DE', {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(date);
};

const formatReleaseType = (release: ArtistRelease) => release.type?.toUpperCase() ?? 'UNKNOWN';

const formatConfidence = (match: ArtistMatch) => {
  if (match.confidence === null || match.confidence === undefined) {
    return '—';
  }
  const pct = Math.round(match.confidence * 100);
  return `${pct}%`;
};

const ArtistDetailPage = () => {
  const params = useParams();
  const artistId = params.id ?? '';
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'overview' | 'releases' | 'matches' | 'activity'>('overview');
  const [releaseFilter, setReleaseFilter] = useState<'all' | 'album' | 'single' | 'ep'>('all');

  const queryKey = useMemo(() => ['artist-detail', artistId], [artistId]);

  const detailQuery = useQuery<ArtistDetailResponse>({
    queryKey,
    queryFn: () => getArtistDetail(artistId),
    enabled: Boolean(artistId),
    refetchInterval: 20000,
    onError: (error) => {
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Artist konnte nicht geladen werden',
        description: 'Bitte erneut versuchen oder Backend prüfen.',
        variant: 'destructive'
      });
    }
  });

  const resyncMutation = useMutation({
    mutationFn: () => enqueueArtistResync(artistId),
    onSuccess: () => {
      toast({
        title: 'Resync gestartet',
        description: 'Der Artist wurde erneut in die Sync-Queue gestellt.'
      });
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Resync fehlgeschlagen',
        description: 'Bitte später erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const invalidateMutation = useMutation({
    mutationFn: () => invalidateArtistCache(artistId),
    onSuccess: () => {
      toast({
        title: 'Cache invalidiert',
        description: 'Die Artist-Daten werden beim nächsten Abruf neu geladen.'
      });
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Invalidate fehlgeschlagen',
        description: 'Bitte später erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  const matchMutation = useMutation({
    mutationFn: ({ matchId, action }: { matchId: string; action: 'accept' | 'reject' }) =>
      updateArtistMatchStatus(artistId, matchId, action),
    onSuccess: (_, variables) => {
      toast({
        title: `Match ${variables.action === 'accept' ? 'akzeptiert' : 'abgelehnt'}`,
        description: 'Die Auswahl wurde gespeichert.'
      });
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.handled) {
        return;
      }
      toast({
        title: 'Aktion fehlgeschlagen',
        description: 'Bitte erneut versuchen.',
        variant: 'destructive'
      });
    }
  });

  if (!artistId) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" disabled>
          <ArrowLeft className="mr-2 h-4 w-4" aria-hidden /> Zurück
        </Button>
        <Card>
          <CardHeader>
            <CardTitle>Kein Artist gewählt</CardTitle>
            <CardDescription>Bitte über die Watchlist einen Artist auswählen.</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (detailQuery.isLoading || !detailQuery.data) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" onClick={() => window.history.back()} className="inline-flex items-center gap-2">
          <ArrowLeft className="h-4 w-4" aria-hidden /> Zurück
        </Button>
        <Card>
          <CardHeader>
            <CardTitle>Artist lädt…</CardTitle>
            <CardDescription>Bitte einen Moment Geduld.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-3 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Daten werden geladen…
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const detail = detailQuery.data;
  const { artist, releases, matches, activity, queue } = detail;
  const filteredReleases = releases.filter((release) => {
    if (releaseFilter === 'all') {
      return true;
    }
    return release.type?.toLowerCase() === releaseFilter;
  });

  const pendingMatches = matches.filter((match) => match.status === 'pending').length;

  const handleMatchAction = (matchId: string, action: 'accept' | 'reject') => {
    void matchMutation.mutate({ matchId, action });
  };

  const renderMatchActions = (match: ArtistMatch) => {
    if (matchMutation.isPending) {
      return <Loader2 className="h-4 w-4 animate-spin" aria-hidden />;
    }
    if (match.status === 'accepted') {
      return (
        <Badge variant="secondary" className="gap-1">
          <Check className="h-3 w-3" aria-hidden /> Akzeptiert
        </Badge>
      );
    }
    if (match.status === 'rejected') {
      return (
        <Badge variant="destructive" className="gap-1">
          <X className="h-3 w-3" aria-hidden /> Abgelehnt
        </Badge>
      );
    }
    return (
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => handleMatchAction(match.id, 'accept')}
        >
          <Check className="mr-1 h-3 w-3" aria-hidden /> Accept
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => handleMatchAction(match.id, 'reject')}>
          <X className="mr-1 h-3 w-3" aria-hidden /> Reject
        </Button>
      </div>
    );
  };

  const renderMatchBadges = (match: ArtistMatch) => {
    if (!match.badges?.length) {
      return null;
    }
    return (
      <div className="flex flex-wrap gap-2">
        {match.badges.map((badge) => (
          <Badge key={`${match.id}-${badge.label}`} variant={badge.tone ?? 'secondary'}>
            {badge.label}
          </Badge>
        ))}
      </div>
    );
  };

  const queueStatus = queue ?? null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => window.history.back()}
            className="inline-flex items-center gap-2"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden /> Zurück
          </Button>
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{artist.name}</h1>
            <p className="text-sm text-muted-foreground">Artist-ID: {artist.id}</p>
          </div>
          {artist.external_ids ? (
            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
              {Object.entries(artist.external_ids).map(([key, value]) => (
                <span key={key} className="rounded bg-muted px-2 py-1">
                  {key}: {value}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        <Card className="min-w-[260px]">
          <CardHeader>
            <CardTitle>Sync-Aktionen</CardTitle>
            <CardDescription>Queue-Status & Trigger.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1 text-sm">
              <div>
                <span className="font-medium">Status:</span>{' '}
                <span className="capitalize">{queueStatus?.status ?? 'unbekannt'}</span>
              </div>
              <div>
                <span className="font-medium">Versuche:</span>{' '}
                {queueStatus?.attempts ?? '—'}
              </div>
              <div>
                <span className="font-medium">ETA:</span> {formatDateTime(queueStatus?.eta)}
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                className="inline-flex items-center gap-2"
                onClick={() => {
                  if (!window.confirm('Resync jetzt starten?')) {
                    return;
                  }
                  void resyncMutation.mutate();
                }}
                disabled={resyncMutation.isPending}
              >
                {resyncMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <RefreshCw className="h-4 w-4" aria-hidden />
                )}
                Resync
              </Button>
              <Button
                type="button"
                variant="outline"
                className="inline-flex items-center gap-2"
                onClick={() => {
                  if (!window.confirm('Cache für diesen Artist invalidieren?')) {
                    return;
                  }
                  void invalidateMutation.mutate();
                }}
                disabled={invalidateMutation.isPending}
              >
                {invalidateMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <ShieldAlert className="h-4 w-4" aria-hidden />
                )}
                Invalidate Cache
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as typeof activeTab)}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="releases">Releases</TabsTrigger>
          <TabsTrigger value="matches">Matches</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Health</CardTitle>
                <CardDescription>Letzter Sync & Zustand</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  {artist.health_status === 'ok' ? (
                    <ShieldCheck className="h-4 w-4 text-emerald-500" aria-hidden />
                  ) : (
                    <ShieldAlert className="h-4 w-4 text-amber-500" aria-hidden />
                  )}
                  <span className="capitalize">{artist.health_status ?? 'unbekannt'}</span>
                </div>
                <div>
                  <span className="font-medium">Zuletzt synchronisiert:</span> {formatDateTime(artist.watchlist?.last_synced_at)}
                </div>
                <div>
                  <span className="font-medium">Nächster Sync:</span> {formatDateTime(artist.watchlist?.next_sync_at)}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Watchlist</CardTitle>
                <CardDescription>Priorität & Intervall</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div>
                  <span className="font-medium">Priorität:</span> {artist.watchlist?.priority ?? '—'}
                </div>
                <div>
                  <span className="font-medium">Intervall:</span>{' '}
                  {artist.watchlist?.interval_days ? `${artist.watchlist.interval_days} Tage` : 'Automatisch'}
                </div>
                <div>
                  <span className="font-medium">Matches offen:</span> {pendingMatches}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Releases</CardTitle>
                <CardDescription>Gesamtbestand</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div>
                  <span className="font-medium">Gesamt:</span> {artist.releases_total ?? releases.length}
                </div>
                <div>
                  <span className="font-medium">Letzte Aktualisierung:</span> {formatDateTime(artist.updated_at)}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        <TabsContent value="releases">
          <Card>
            <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <CardTitle>Releases</CardTitle>
                <CardDescription>Gefundene Veröffentlichungen nach Typ filtern.</CardDescription>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <label htmlFor="release-filter" className="text-muted-foreground">
                  Filter
                </label>
                <select
                  id="release-filter"
                  className="rounded border bg-background px-2 py-1"
                  value={releaseFilter}
                  onChange={(event) => setReleaseFilter(event.target.value as typeof releaseFilter)}
                >
                  <option value="all">Alle</option>
                  <option value="album">Album</option>
                  <option value="single">Single</option>
                  <option value="ep">EP</option>
                </select>
              </div>
            </CardHeader>
            <CardContent>
              {filteredReleases.length ? (
                <ScrollArea className="h-[360px] pr-4">
                  <ul className="space-y-4">
                    {filteredReleases.map((release) => (
                      <li key={release.id} className="rounded border p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <h3 className="text-base font-medium">{release.title}</h3>
                            <p className="text-sm text-muted-foreground">{formatReleaseType(release)}</p>
                          </div>
                          <div className="text-sm text-muted-foreground">{formatDateTime(release.released_at)}</div>
                        </div>
                        {release.spotify_url ? (
                          <a
                            className="mt-2 inline-flex text-sm text-primary hover:underline"
                            href={release.spotify_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Spotify öffnen
                          </a>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </ScrollArea>
              ) : (
                <div className="py-10 text-center text-sm text-muted-foreground">Keine Releases gefunden.</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="matches">
          <Card>
            <CardHeader>
              <CardTitle>Matches</CardTitle>
              <CardDescription>Treffer kuratieren und Entscheidungen treffen.</CardDescription>
            </CardHeader>
            <CardContent>
              {matches.length ? (
                <div className="space-y-4">
                  {matches
                    .slice()
                    .sort((a, b) => MATCH_STATUS_ORDER.indexOf(a.status) - MATCH_STATUS_ORDER.indexOf(b.status))
                    .map((match) => (
                      <div key={match.id} className="rounded border p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="space-y-1">
                            <div className="text-sm text-muted-foreground">{match.provider ?? 'Unbekannte Quelle'}</div>
                            <h3 className="text-lg font-semibold">{match.title}</h3>
                            <p className="text-sm text-muted-foreground">
                              Release: {match.release_title ?? 'n/a'} · Confidence {formatConfidence(match)}
                            </p>
                            {renderMatchBadges(match)}
                          </div>
                          <div className="text-right text-xs text-muted-foreground">
                            Eingereicht: {formatDateTime(match.submitted_at)}
                          </div>
                        </div>
                        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                          <Badge variant="outline" className="capitalize">
                            Status: {match.status}
                          </Badge>
                          {renderMatchActions(match)}
                        </div>
                      </div>
                    ))}
                </div>
              ) : (
                <div className="py-10 text-center text-sm text-muted-foreground">
                  Keine Matches gefunden.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="activity">
          <Card>
            <CardHeader>
              <CardTitle>Aktivität</CardTitle>
              <CardDescription>Chronologisches Log der letzten Ereignisse.</CardDescription>
            </CardHeader>
            <CardContent>
              {activity.length ? (
                <ScrollArea className="h-[360px] pr-4" aria-label="Aktivitätenliste">
                  <ol className="space-y-4 text-sm">
                    {activity.map((item) => (
                      <li key={item.id} className="flex gap-3">
                        <div className="mt-1 h-2 w-2 flex-none rounded-full bg-primary" aria-hidden />
                        <div className="space-y-1">
                          <div className="font-medium">{item.message}</div>
                          <div className="text-xs text-muted-foreground">
                            {formatDateTime(item.created_at)} · {item.category ?? 'Event'}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                </ScrollArea>
              ) : (
                <div className="py-10 text-center text-sm text-muted-foreground">Noch keine Aktivitäten vorhanden.</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default ArtistDetailPage;
