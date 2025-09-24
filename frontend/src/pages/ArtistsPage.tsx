import { useEffect, useMemo, useState } from 'react';
import { Loader2, Users } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { ScrollArea } from '../components/ui/scroll-area';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Switch } from '../components/ui/switch';
import { useToast } from '../hooks/useToast';
import {
  ArtistPreferenceEntry,
  fetchArtistPreferences,
  fetchArtistReleases,
  fetchFollowedArtists,
  saveArtistPreferences,
  SpotifyArtist,
  SpotifyArtistRelease
} from '../lib/api';
import { useMutation, useQuery } from '../lib/query';

const toTitleCase = (value?: string | null) => {
  if (!value) {
    return 'Unbekannt';
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
};

const getReleaseYear = (value?: string | null) => {
  if (!value) {
    return '—';
  }
  const year = value.slice(0, 4);
  return year || '—';
};

const extractImageUrl = (artist: SpotifyArtist) => {
  const image = artist.images?.find((item) => Boolean(item?.url));
  return image?.url ?? '';
};

const areSelectionsEqual = (a: Record<string, boolean>, b: Record<string, boolean>) => {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) {
    if (Boolean(a[key]) !== Boolean(b[key])) {
      return false;
    }
  }
  return true;
};

const ArtistsPage = () => {
  const { toast } = useToast();
  const [selectedArtistId, setSelectedArtistId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [releaseCounts, setReleaseCounts] = useState<Record<string, number>>({});

  const {
    data: artists,
    isLoading: isLoadingArtists
  } = useQuery<SpotifyArtist[]>({
    queryKey: ['spotify-followed-artists'],
    queryFn: fetchFollowedArtists,
    onError: () =>
      toast({
        title: 'Artists konnten nicht geladen werden',
        description: 'Bitte Backend-Verbindung prüfen.',
        variant: 'destructive'
      })
  });

  const {
    data: preferences,
    refetch: refetchPreferences
  } = useQuery<ArtistPreferenceEntry[]>({
    queryKey: ['artist-preferences'],
    queryFn: fetchArtistPreferences,
    onError: () =>
      toast({
        title: 'Artist-Präferenzen fehlgeschlagen',
        description: 'Die Auswahl konnte nicht geladen werden.',
        variant: 'destructive'
      })
  });

  const {
    data: releases,
    isLoading: isLoadingReleases,
    refetch: refetchReleases
  } = useQuery<SpotifyArtistRelease[]>({
    queryKey: ['artist-releases', selectedArtistId ?? 'none'],
    queryFn: () => {
      if (!selectedArtistId) {
        return Promise.resolve<SpotifyArtistRelease[]>([]);
      }
      return fetchArtistReleases(selectedArtistId);
    },
    onError: () =>
      toast({
        title: 'Releases konnten nicht geladen werden',
        description: 'Bitte versuchen Sie es erneut.',
        variant: 'destructive'
      })
  });

  const baseSelection = useMemo(() => {
    if (!selectedArtistId) {
      return {};
    }
    const relevantPreferences = (preferences ?? []).filter((entry) => entry.artist_id === selectedArtistId);
    const preferenceMap = new Map(relevantPreferences.map((entry) => [entry.release_id, entry.selected]));
    const nextSelection: Record<string, boolean> = {};
    (releases ?? []).forEach((release) => {
      if (release.id) {
        nextSelection[release.id] = preferenceMap.get(release.id) ?? false;
      }
    });
    return nextSelection;
  }, [preferences, releases, selectedArtistId]);

  useEffect(() => {
    if (!selectedArtistId) {
      setSelection({});
      return;
    }
    setSelection((previous) => {
      if (areSelectionsEqual(previous, baseSelection)) {
        return previous;
      }
      return baseSelection;
    });
  }, [baseSelection, selectedArtistId]);

  useEffect(() => {
    if (!selectedArtistId) {
      return;
    }
    const count = releases?.length ?? 0;
    setReleaseCounts((prev) => {
      if (prev[selectedArtistId] === count) {
        return prev;
      }
      return { ...prev, [selectedArtistId]: count };
    });
  }, [releases, selectedArtistId]);

  const savePreferencesMutation = useMutation({
    mutationFn: saveArtistPreferences,
    onSuccess: () => {
      toast({
        title: 'Präferenzen gespeichert',
        description: 'Die Auswahl wurde erfolgreich aktualisiert.'
      });
      void refetchPreferences();
      void refetchReleases();
    },
    onError: () => {
      toast({
        title: 'Speichern fehlgeschlagen',
        description: 'Die Auswahl konnte nicht gespeichert werden.',
        variant: 'destructive'
      });
    }
  });

  const sortedArtists = useMemo(() => {
    return [...(artists ?? [])].sort((a, b) => {
      const nameA = a.name ?? '';
      const nameB = b.name ?? '';
      return nameA.localeCompare(nameB);
    });
  }, [artists]);

  const selectedArtist = useMemo(
    () => sortedArtists.find((artist) => artist.id === selectedArtistId) ?? null,
    [sortedArtists, selectedArtistId]
  );

  const releaseRows = useMemo(() => releases ?? [], [releases]);

  const currentSelection = selection;
  const isDirty = useMemo(
    () => !areSelectionsEqual(currentSelection, baseSelection),
    [baseSelection, currentSelection]
  );

  const handleToggle = (releaseId: string, value: boolean) => {
    setSelection((prev) => ({ ...prev, [releaseId]: value }));
  };

  const handleSave = () => {
    if (!selectedArtistId) {
      return;
    }
    const payload = Object.entries(selection).map(([releaseId, selected]) => ({
      artist_id: selectedArtistId,
      release_id: releaseId,
      selected
    }));
    if (payload.length === 0) {
      toast({
        title: 'Keine Releases zum Speichern',
        description: 'Für diesen Artist liegen keine auswählbaren Releases vor.'
      });
      return;
    }
    void savePreferencesMutation.mutate(payload);
  };

  const renderArtistList = () => {
    if (isLoadingArtists) {
      return (
        <div className="flex items-center justify-center py-8 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      );
    }

    if (!sortedArtists.length) {
      return <p className="text-sm text-muted-foreground">Keine Artists gefunden.</p>;
    }

    return (
      <ul className="space-y-2">
        {sortedArtists.map((artist) => {
          const isActive = artist.id === selectedArtistId;
          const imageUrl = extractImageUrl(artist);
          const count = releaseCounts[artist.id];
          return (
            <li key={artist.id}>
              <button
                type="button"
                onClick={() => setSelectedArtistId(artist.id)}
                className={`flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors hover:border-primary hover:bg-primary/5 ${
                  isActive ? 'border-primary bg-primary/10' : 'border-border'
                }`}
              >
                {imageUrl ? (
                  <img src={imageUrl} alt="Artist Cover" className="h-10 w-10 rounded-md object-cover" />
                ) : (
                  <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <Users className="h-5 w-5" />
                  </div>
                )}
                <div className="flex flex-1 flex-col">
                  <span className="text-sm font-medium">{artist.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {typeof count === 'number' ? `${count} Releases` : 'Releases unbekannt'}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    );
  };

  const renderReleaseTable = () => {
    if (!selectedArtistId) {
      return <p className="text-sm text-muted-foreground">Bitte wählen Sie einen Artist aus.</p>;
    }

    if (isLoadingReleases) {
      return (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      );
    }

    if (!releaseRows.length) {
      return <p className="text-sm text-muted-foreground">Keine Releases verfügbar.</p>;
    }

    return (
      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Titel</TableHead>
              <TableHead>Typ</TableHead>
              <TableHead>Erscheinungsjahr</TableHead>
              <TableHead>Tracks</TableHead>
              <TableHead className="text-right">Für Sync aktivieren</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {releaseRows.map((release) => {
              const isSelected = selection[release.id] ?? false;
              return (
                <TableRow key={release.id}>
                  <TableCell className="font-medium">{release.name}</TableCell>
                  <TableCell>{toTitleCase(release.album_type)}</TableCell>
                  <TableCell>{getReleaseYear(release.release_date)}</TableCell>
                  <TableCell>{release.total_tracks ?? '—'}</TableCell>
                  <TableCell className="text-right">
                    <Switch
                      checked={isSelected}
                      onCheckedChange={(value) => handleToggle(release.id, value)}
                      aria-label={`Sync für ${release.name}`}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Gefolgte Artists</CardTitle>
          <CardDescription>Verwalten Sie, welche Releases automatisch synchronisiert werden sollen.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
            <ScrollArea className="max-h-[540px] rounded-lg border p-4">
              {renderArtistList()}
            </ScrollArea>
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold">
                  {selectedArtist ? selectedArtist.name : 'Keine Auswahl'}
                </h2>
                <p className="text-sm text-muted-foreground">
                  {selectedArtist
                    ? 'Aktivieren Sie Releases, die vom AutoSync berücksichtigt werden sollen.'
                    : 'Wählen Sie links einen Artist aus, um verfügbare Releases zu sehen.'}
                </p>
              </div>
              {renderReleaseTable()}
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setSelection(baseSelection)} disabled={!isDirty}>
                  Änderungen verwerfen
                </Button>
                <Button
                  onClick={handleSave}
                  disabled={!selectedArtistId || !isDirty || savePreferencesMutation.isPending}
                >
                  {savePreferencesMutation.isPending ? (
                    <span className="inline-flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Wird gespeichert...
                    </span>
                  ) : (
                    'Änderungen speichern'
                  )}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default ArtistsPage;
