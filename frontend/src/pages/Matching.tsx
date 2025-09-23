import { FormEvent, useState } from "react";
import { Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { useToast } from "../components/ui/use-toast";
import matchingService, { MatchingResponse } from "../services/matching";

const emptyResponse: MatchingResponse = { bestMatch: null, confidence: 0 };

const parseJson = (value: string) => {
  try {
    return value ? JSON.parse(value) : null;
  } catch (error) {
    throw new Error("Ungültiges JSON");
  }
};

const defaultSpotifyTrack = JSON.stringify(
  {
    id: "spotify:track:example",
    name: "Example Track",
    artists: [{ name: "Example Artist" }],
    album: { name: "Example Album" }
  },
  null,
  2
);

const defaultCandidates = JSON.stringify(
  [
    { id: "candidate-1", title: "Example Candidate", artist: "Example Artist" }
  ],
  null,
  2
);

const Matching = () => {
  const { toast } = useToast();
  const [spotifyTrack, setSpotifyTrack] = useState(defaultSpotifyTrack);
  const [plexCandidates, setPlexCandidates] = useState(defaultCandidates);
  const [soulseekCandidates, setSoulseekCandidates] = useState(defaultCandidates);
  const [plexResult, setPlexResult] = useState<MatchingResponse>(emptyResponse);
  const [soulseekResult, setSoulseekResult] = useState<MatchingResponse>(emptyResponse);
  const [loading, setLoading] = useState<"plex" | "soulseek" | null>(null);

  const runMatching = async (type: "plex" | "soulseek") => {
    try {
      setLoading(type);
      const track = parseJson(spotifyTrack);
      const candidates = parseJson(type === "plex" ? plexCandidates : soulseekCandidates);
      if (!track || !Array.isArray(candidates)) {
        throw new Error("Track oder Kandidaten fehlen");
      }
      const payload = { spotify_track: track, candidates };
      if (type === "plex") {
        const result = await matchingService.matchSpotifyToPlex(payload);
        setPlexResult(result);
        toast({ title: "Matching abgeschlossen", description: "Spotify ↔ Plex Ergebnis aktualisiert." });
      } else {
        const result = await matchingService.matchSpotifyToSoulseek(payload);
        setSoulseekResult(result);
        toast({ title: "Matching abgeschlossen", description: "Spotify ↔ Soulseek Ergebnis aktualisiert." });
      }
    } catch (error) {
      console.error(error);
      toast({ title: "Matching fehlgeschlagen", description: String(error), variant: "destructive" });
    } finally {
      setLoading(null);
    }
  };

  const handleSubmit = (type: "plex" | "soulseek") => (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void runMatching(type);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Matching</h1>
        <p className="text-sm text-muted-foreground">
          Vergleiche Spotify-Tracks mit Plex- oder Soulseek-Kandidaten. Füge JSON-Payloads ein, um die API direkt zu testen.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Spotify → Plex</CardTitle>
            <CardDescription>Berechne den besten Plex-Match für einen Spotify-Track.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit("plex")}>
              <div className="space-y-2">
                <Label htmlFor="spotifyTrackPlex">Spotify Track (JSON)</Label>
                <Textarea
                  id="spotifyTrackPlex"
                  value={spotifyTrack}
                  onChange={(event) => setSpotifyTrack(event.target.value)}
                  rows={6}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="plexCandidates">Plex Kandidaten (JSON Array)</Label>
                <Textarea
                  id="plexCandidates"
                  value={plexCandidates}
                  onChange={(event) => setPlexCandidates(event.target.value)}
                  rows={6}
                />
              </div>
              <Button type="submit" disabled={loading !== null}>
                {loading === "plex" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Matching starten
              </Button>
            </form>
            <div className="mt-6 space-y-2">
              <h3 className="text-sm font-semibold">Ergebnis</h3>
              <pre className="max-h-48 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
                {JSON.stringify(plexResult.bestMatch, null, 2) || "—"}
              </pre>
              <p className="text-sm text-muted-foreground">Confidence: {plexResult.confidence.toFixed(2)}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Spotify → Soulseek</CardTitle>
            <CardDescription>Bewerte Soulseek-Kandidaten auf Basis der Harmony-Engine.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit("soulseek")}>
              <div className="space-y-2">
                <Label htmlFor="spotifyTrackSoulseek">Spotify Track (JSON)</Label>
                <Textarea
                  id="spotifyTrackSoulseek"
                  value={spotifyTrack}
                  onChange={(event) => setSpotifyTrack(event.target.value)}
                  rows={6}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="soulseekCandidates">Soulseek Kandidaten (JSON Array)</Label>
                <Textarea
                  id="soulseekCandidates"
                  value={soulseekCandidates}
                  onChange={(event) => setSoulseekCandidates(event.target.value)}
                  rows={6}
                />
              </div>
              <Button type="submit" disabled={loading !== null}>
                {loading === "soulseek" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Matching starten
              </Button>
            </form>
            <div className="mt-6 space-y-2">
              <h3 className="text-sm font-semibold">Ergebnis</h3>
              <pre className="max-h-48 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
                {JSON.stringify(soulseekResult.bestMatch, null, 2) || "—"}
              </pre>
              <p className="text-sm text-muted-foreground">Confidence: {soulseekResult.confidence.toFixed(2)}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Zusammenfassung</CardTitle>
          <CardDescription>Vergleiche die letzten Ergebnisse der Matching-Aufrufe.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Treffer</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>Spotify → Plex</TableCell>
                <TableCell>{plexResult.confidence.toFixed(2)}</TableCell>
                <TableCell>{plexResult.bestMatch ? "✅" : "—"}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Spotify → Soulseek</TableCell>
                <TableCell>{soulseekResult.confidence.toFixed(2)}</TableCell>
                <TableCell>{soulseekResult.bestMatch ? "✅" : "—"}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

export default Matching;
