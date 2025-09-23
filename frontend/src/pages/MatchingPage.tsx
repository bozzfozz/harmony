import { useCallback, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Textarea } from '../components/ui/textarea';
import { Button } from '../components/ui/button';
import { useToast } from '../hooks/useToast';
import { useMutation } from '../lib/query';
import {
  runSpotifyToPlexAlbumMatch,
  runSpotifyToPlexMatch,
  runSpotifyToSoulseekMatch,
  MatchingResponsePayload
} from '../lib/api';

const stringifyResult = (result: MatchingResponsePayload | undefined) => {
  if (!result) {
    return 'No result yet.';
  }
  return JSON.stringify(result, null, 2);
};

const MatchingPage = () => {
  const { toast } = useToast();
  const [trackInput, setTrackInput] = useState('{}');
  const [candidateInput, setCandidateInput] = useState('[]');
  const [albumInput, setAlbumInput] = useState('{}');
  const [albumCandidatesInput, setAlbumCandidatesInput] = useState('[]');

  const spotifyToPlexMutation = useMutation({
    mutationFn: runSpotifyToPlexMatch,
    onError: () =>
      toast({
        title: 'Matching failed',
        description: 'Plex candidates could not be evaluated.',
        variant: 'destructive'
      })
  });

  const spotifyToSoulseekMutation = useMutation({
    mutationFn: runSpotifyToSoulseekMatch,
    onError: () =>
      toast({
        title: 'Matching failed',
        description: 'Soulseek candidates could not be evaluated.',
        variant: 'destructive'
      })
  });

  const spotifyToPlexAlbumMutation = useMutation({
    mutationFn: runSpotifyToPlexAlbumMatch,
    onError: () =>
      toast({
        title: 'Album matching failed',
        description: 'Album candidates could not be evaluated.',
        variant: 'destructive'
      })
  });

  const parseJson = useCallback(
    (label: string, value: string) => {
      try {
        return JSON.parse(value);
      } catch (error) {
        console.error(`Failed to parse ${label}`, error);
        toast({
          title: `Invalid ${label}`,
          description: 'Please provide valid JSON input.',
          variant: 'destructive'
        });
        throw error;
      }
    },
    [toast]
  );

  const handleSpotifyToPlex = async () => {
    try {
      const track = parseJson('Spotify track', trackInput);
      const candidates = parseJson('Plex candidates', candidateInput);
      if (!Array.isArray(candidates)) {
        toast({
          title: 'Invalid candidates',
          description: 'Candidates must be provided as a JSON array.',
          variant: 'destructive'
        });
        return;
      }
      await spotifyToPlexMutation.mutate({
        spotify_track: track,
        candidates
      });
      toast({ title: 'Matching completed', description: 'Best Plex match calculated.' });
    } catch (error) {
      // Error already handled via toast in parseJson or mutation onError.
    }
  };

  const handleSpotifyToSoulseek = async () => {
    try {
      const track = parseJson('Spotify track', trackInput);
      const candidates = parseJson('Soulseek candidates', candidateInput);
      if (!Array.isArray(candidates)) {
        toast({
          title: 'Invalid candidates',
          description: 'Candidates must be provided as a JSON array.',
          variant: 'destructive'
        });
        return;
      }
      await spotifyToSoulseekMutation.mutate({
        spotify_track: track,
        candidates
      });
      toast({ title: 'Matching completed', description: 'Best Soulseek match calculated.' });
    } catch (error) {
      // Error already handled via toast in parseJson or mutation onError.
    }
  };

  const handleAlbumMatch = async () => {
    try {
      const album = parseJson('Spotify album', albumInput);
      const candidates = parseJson('Album candidates', albumCandidatesInput);
      if (!Array.isArray(candidates)) {
        toast({
          title: 'Invalid candidates',
          description: 'Candidates must be provided as a JSON array.',
          variant: 'destructive'
        });
        return;
      }
      await spotifyToPlexAlbumMutation.mutate({
        spotify_album: album,
        candidates
      });
      toast({
        title: 'Album matching completed',
        description: 'Best Plex album match calculated.'
      });
    } catch (error) {
      // Error already handled via toast in parseJson or mutation onError.
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Track matching</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-sm font-medium">Spotify track (JSON)</p>
            <Textarea
              value={trackInput}
              onChange={(event) => setTrackInput(event.target.value)}
              rows={6}
              placeholder='{"name": "Song", "id": "spotify:track:123"}'
            />
          </div>
          <div>
            <p className="text-sm font-medium">Candidate list (JSON array)</p>
            <Textarea
              value={candidateInput}
              onChange={(event) => setCandidateInput(event.target.value)}
              rows={6}
              placeholder='[{"title": "Song", "ratingKey": "42"}]'
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={handleSpotifyToPlex} disabled={spotifyToPlexMutation.isPending}>
              {spotifyToPlexMutation.isPending ? (
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Matching Plex…
                </span>
              ) : (
                'Match with Plex'
              )}
            </Button>
            <Button
              variant="outline"
              onClick={handleSpotifyToSoulseek}
              disabled={spotifyToSoulseekMutation.isPending}
            >
              {spotifyToSoulseekMutation.isPending ? (
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Matching Soulseek…
                </span>
              ) : (
                'Match with Soulseek'
              )}
            </Button>
          </div>
          <div>
            <p className="text-sm font-medium">Latest result</p>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md border bg-muted p-3 text-xs">
              {stringifyResult(spotifyToPlexMutation.data ?? spotifyToSoulseekMutation.data)}
            </pre>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Album matching</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-sm font-medium">Spotify album (JSON)</p>
            <Textarea
              value={albumInput}
              onChange={(event) => setAlbumInput(event.target.value)}
              rows={6}
              placeholder='{"name": "Album", "id": "spotify:album:456"}'
            />
          </div>
          <div>
            <p className="text-sm font-medium">Plex album candidates (JSON array)</p>
            <Textarea
              value={albumCandidatesInput}
              onChange={(event) => setAlbumCandidatesInput(event.target.value)}
              rows={6}
              placeholder='[{"title": "Album", "ratingKey": "84"}]'
            />
          </div>
          <Button onClick={handleAlbumMatch} disabled={spotifyToPlexAlbumMutation.isPending}>
            {spotifyToPlexAlbumMutation.isPending ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Matching album…
              </span>
            ) : (
              'Match album with Plex'
            )}
          </Button>
          <div>
            <p className="text-sm font-medium">Latest album result</p>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md border bg-muted p-3 text-xs">
              {stringifyResult(spotifyToPlexAlbumMutation.data)}
            </pre>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default MatchingPage;
