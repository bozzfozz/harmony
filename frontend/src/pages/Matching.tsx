import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { useToast } from "../components/ui/use-toast";
import matchingService, { MatchingSummary } from "../services/matching";

const Matching = () => {
  const { toast } = useToast();
  const [spotifyToPlex, setSpotifyToPlex] = useState<MatchingSummary | null>(null);
  const [spotifyToSoulseek, setSpotifyToSoulseek] = useState<MatchingSummary | null>(null);
  const [loading, setLoading] = useState<"plex" | "soulseek" | null>(null);

  const handleMatch = async (type: "plex" | "soulseek") => {
    try {
      setLoading(type);
      if (type === "plex") {
        const result = await matchingService.matchSpotifyToPlex();
        setSpotifyToPlex(result);
        toast({ title: "Matching gestartet", description: "Spotify ↔ Plex abgeglichen" });
      } else {
        const result = await matchingService.matchSpotifyToSoulseek();
        setSpotifyToSoulseek(result);
        toast({ title: "Matching gestartet", description: "Spotify ↔ Soulseek abgeglichen" });
      }
    } catch (error) {
      console.error(error);
      toast({
        title: "Matching fehlgeschlagen",
        variant: "destructive"
      });
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Matching</h1>
        <p className="text-sm text-muted-foreground">
          Starte Abgleiche zwischen Spotify, Plex und Soulseek, um fehlende Inhalte schnell zu finden.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Automatisierte Abgleiche</CardTitle>
          <CardDescription>Starte Matching-Läufe und verfolge die Ergebnisse.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-border p-4">
            <h3 className="text-lg font-semibold">Spotify → Plex</h3>
            <p className="mb-3 text-sm text-muted-foreground">
              Vergleicht deine Spotify-Playlists mit der Plex-Bibliothek.
            </p>
            <Button onClick={() => void handleMatch("plex")} disabled={loading !== null}>
              {loading === "plex" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Matching starten
            </Button>
            {spotifyToPlex && (
              <div className="mt-4 space-y-1 text-sm">
                <p className="font-medium">Ergebnis</p>
                <p>Gefunden: {spotifyToPlex.matched}</p>
                <p>Fehlend: {spotifyToPlex.missing}</p>
                {spotifyToPlex.lastRun ? <p>Letzter Lauf: {new Date(spotifyToPlex.lastRun).toLocaleString()}</p> : null}
              </div>
            )}
          </div>

          <div className="rounded-lg border border-border p-4">
            <h3 className="text-lg font-semibold">Spotify → Soulseek</h3>
            <p className="mb-3 text-sm text-muted-foreground">
              Prüft, welche Tracks in Soulseek verfügbar sind.
            </p>
            <Button onClick={() => void handleMatch("soulseek")} disabled={loading !== null}>
              {loading === "soulseek" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Matching starten
            </Button>
            {spotifyToSoulseek && (
              <div className="mt-4 space-y-1 text-sm">
                <p className="font-medium">Ergebnis</p>
                <p>Gefunden: {spotifyToSoulseek.matched}</p>
                <p>Fehlend: {spotifyToSoulseek.missing}</p>
                {spotifyToSoulseek.lastRun ? (
                  <p>Letzter Lauf: {new Date(spotifyToSoulseek.lastRun).toLocaleString()}</p>
                ) : null}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Letzte Ergebnisse</CardTitle>
          <CardDescription>Zusammenfassung der letzten Matching-Läufe.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Gefunden</TableHead>
                <TableHead>Fehlend</TableHead>
                <TableHead>Zuletzt</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>Spotify → Plex</TableCell>
                <TableCell>{spotifyToPlex?.matched ?? "—"}</TableCell>
                <TableCell>{spotifyToPlex?.missing ?? "—"}</TableCell>
                <TableCell>
                  {spotifyToPlex?.lastRun ? new Date(spotifyToPlex.lastRun).toLocaleString() : "—"}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Spotify → Soulseek</TableCell>
                <TableCell>{spotifyToSoulseek?.matched ?? "—"}</TableCell>
                <TableCell>{spotifyToSoulseek?.missing ?? "—"}</TableCell>
                <TableCell>
                  {spotifyToSoulseek?.lastRun ? new Date(spotifyToSoulseek.lastRun).toLocaleString() : "—"}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

export default Matching;
