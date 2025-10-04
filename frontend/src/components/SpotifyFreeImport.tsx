import { ChangeEvent, useRef, useState } from 'react';
import { Loader2, Upload } from 'lucide-react';

import {
  enqueueSpotifyFreeTracks,
  NormalizedTrack,
  parseSpotifyFreeInput,
  SpotifyFreeEnqueueResponse,
  SpotifyFreeParsePayload,
  SpotifyFreeUploadPayload,
  uploadSpotifyFreeFile
} from '../api/services/spotify';
import { ApiError } from '../api/client';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Input
} from './ui/shadcn';
import { Label } from './ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Textarea } from './ui/textarea';
import { useToast } from '../hooks/useToast';

const normaliseQuery = (track: NormalizedTrack): string => {
  const segments = [track.title.trim(), track.artist.trim()];
  if (track.album) {
    segments.push(track.album.trim());
  }
  if (track.release_year) {
    segments.push(String(track.release_year));
  }
  return segments.filter(Boolean).join(' ');
};

const SpotifyFreeImport = () => {
  const { toast } = useToast();
  const [input, setInput] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileToken, setFileToken] = useState<string | null>(null);
  const [items, setItems] = useState<NormalizedTrack[]>([]);
  const [isParsing, setIsParsing] = useState(false);
  const [isEnqueuing, setIsEnqueuing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const hasItems = items.length > 0;

  const helperText =
    'Importiere Spotify-Listen ohne OAuth: Eine Referenz pro Zeile ("Artist - Title | Album | Year") oder Spotify-Track-Link.';

  const handleUploadChange = async (event: ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files || event.target.files.length === 0) {
      return;
    }
    const file = event.target.files[0];
    try {
      const content = await file.text();
      const payload: SpotifyFreeUploadPayload = { filename: file.name, content };
      const response = await uploadSpotifyFreeFile(payload);
      setFileToken(response.file_token);
      setFileName(file.name);
      toast({ title: 'Datei übernommen', description: `${file.name} bereit zum Parsen.` });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Datei konnte nicht verarbeitet werden.';
      toast({ title: 'Upload fehlgeschlagen', description: message, variant: 'destructive' });
      setFileToken(null);
      setFileName(null);
    } finally {
      event.target.value = '';
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handlePreview = async () => {
    const payload: SpotifyFreeParsePayload = {
      lines: input
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
    };
    if (fileToken) {
      payload.file_token = fileToken;
    }
    setIsParsing(true);
    try {
      const response = await parseSpotifyFreeInput(payload);
      const parsed = response.items.map((item) => ({ ...item, query: normaliseQuery(item) }));
      setItems(parsed);
      toast({
        title: 'Parser erfolgreich',
        description: `${parsed.length} Titel erkannt. Bitte prüfen und bei Bedarf anpassen.`
      });
    } catch (error) {
      if (error instanceof ApiError) {
        toast({ title: 'Parser-Fehler', description: error.message, variant: 'destructive' });
      } else {
        toast({ title: 'Parser-Fehler', description: 'Unbekannter Fehler beim Parsen.', variant: 'destructive' });
      }
      setItems([]);
    } finally {
      setIsParsing(false);
    }
  };

  const handleItemChange = (index: number, key: keyof NormalizedTrack, value: string) => {
    setItems((previous) => {
      const updated = [...previous];
      const current = { ...updated[index] };
      if (key === 'release_year') {
        const numeric = value.trim();
        current.release_year = numeric === '' ? null : Number(numeric);
      } else {
        current[key] = value as never;
      }
      current.query = normaliseQuery(current);
      updated[index] = current;
      return updated;
    });
  };

  const handleEnqueue = async () => {
    if (!hasItems) {
      toast({ title: 'Keine Titel', description: 'Bitte zuerst Tracks importieren.', variant: 'destructive' });
      return;
    }
    setIsEnqueuing(true);
    try {
      const response: SpotifyFreeEnqueueResponse = await enqueueSpotifyFreeTracks({ items });
      const description = `Downloads geplant: ${response.queued}. Übersprungen: ${response.skipped}.`;
      toast({ title: 'Jobs eingereiht', description });
    } catch (error) {
      if (error instanceof ApiError) {
        toast({ title: 'Enqueue fehlgeschlagen', description: error.message, variant: 'destructive' });
      } else {
        toast({ title: 'Enqueue fehlgeschlagen', description: 'Unbekannter Fehler beim Einreihen.', variant: 'destructive' });
      }
    } finally {
      setIsEnqueuing(false);
    }
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Spotify FREE Import</CardTitle>
        <CardDescription>{helperText}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="spotify-free-text">Manuelle Eingabe</Label>
            <Textarea
              id="spotify-free-text"
              placeholder="Artist - Title | Album | Year"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              className="min-h-[140px]"
            />
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Mehrere Einträge getrennt durch Zeilenumbrüche. Optional können Spotify-Track-Links angefügt werden.
            </p>
          </div>
          <div className="space-y-3">
            <Label>Dateiupload (.txt, .m3u, .m3u8)</Label>
            <Button
              type="button"
              variant="outline"
              className="w-full justify-center"
              onClick={handleUploadClick}
            >
              <span className="flex items-center justify-center gap-2">
                <Upload className="h-4 w-4" />
                <span>Datei auswählen</span>
              </span>
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.m3u,.m3u8"
              className="hidden"
              onChange={handleUploadChange}
            />
            {fileName && <p className="text-xs text-slate-500 dark:text-slate-400">Aktiv: {fileName}</p>}
            <Button type="button" onClick={handlePreview} disabled={isParsing} className="w-full">
              {isParsing ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Parser läuft …
                </span>
              ) : (
                'Vorschau erstellen'
              )}
            </Button>
          </div>
        </div>

        {hasItems ? (
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Artist</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>Album</TableHead>
                  <TableHead>Year</TableHead>
                  <TableHead>Spotify Track ID</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item, index) => (
                  <TableRow key={`${item.query}-${index}`}>
                    <TableCell className="min-w-[160px]">
                      <Input
                        value={item.artist}
                        onChange={(event) => handleItemChange(index, 'artist', event.target.value)}
                      />
                    </TableCell>
                    <TableCell className="min-w-[160px]">
                      <Input
                        value={item.title}
                        onChange={(event) => handleItemChange(index, 'title', event.target.value)}
                      />
                    </TableCell>
                    <TableCell className="min-w-[160px]">
                      <Input
                        value={item.album ?? ''}
                        onChange={(event) => handleItemChange(index, 'album', event.target.value)}
                      />
                    </TableCell>
                    <TableCell className="w-24">
                      <Input
                        value={item.release_year ?? ''}
                        onChange={(event) => handleItemChange(index, 'release_year', event.target.value)}
                        inputMode="numeric"
                      />
                    </TableCell>
                    <TableCell className="min-w-[160px]">
                      <Input
                        value={item.spotify_track_id ?? ''}
                        onChange={(event) => handleItemChange(index, 'spotify_track_id', event.target.value)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
            Noch keine Vorschau. Füge Eingaben hinzu oder lade eine Datei hoch und starte den Parser.
          </p>
        )}
      </CardContent>
      <CardFooter className="justify-between gap-4">
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {hasItems ? `${items.length} Einträge vorbereitet.` : 'Keine Einträge geladen.'}
        </div>
        <Button type="button" disabled={!hasItems || isEnqueuing} onClick={handleEnqueue}>
          {isEnqueuing ? (
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Jobs werden erstellt …
            </span>
          ) : (
            'Downloads einreihen'
          )}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default SpotifyFreeImport;
