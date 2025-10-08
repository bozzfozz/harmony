import { FormEvent, useId, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { extractPlaylistId, isSpotifyPlaylistLink } from '../../lib/validators/spotifyLink';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from '../ui/shadcn';
import { Label } from '../ui/label';
import { Textarea } from '../ui/textarea';

const splitLinks = (value: string): string[] => {
  return value
    .split(/\r?\n/u)
    .flatMap((line) => line.split(/[\s,;]+/u))
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
};

const dedupeLinks = (links: string[]): string[] => {
  const result: string[] = [];
  const seen = new Set<string>();

  links.forEach((link) => {
    const playlistId = extractPlaylistId(link);
    const key = playlistId ? `id:${playlistId.toLowerCase()}` : `url:${link.toLowerCase()}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    result.push(link);
  });

  return result;
};

export interface FreeLinksFormProps {
  onSubmit: (links: string[]) => Promise<void> | void;
  isSubmitting?: boolean;
}

const FreeLinksForm = ({ onSubmit, isSubmitting = false }: FreeLinksFormProps) => {
  const textareaId = useId();
  const errorId = useId();
  const [value, setValue] = useState('');
  const [invalidLinks, setInvalidLinks] = useState<string[]>([]);

  const helperText =
    'Füge hier einen oder mehrere Spotify-Playlist-Links ein. Mehrere Einträge können durch Zeilenumbrüche getrennt werden.';

  const placeholder = useMemo(
    () =>
      ['https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M', 'spotify:playlist:37i9dQZF1DX4JAvHpjipBk'].join('\n'),
    []
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const links = splitLinks(value);
    if (links.length === 0) {
      setInvalidLinks(['Bitte gib mindestens einen Spotify-Playlist-Link ein.']);
      return;
    }

    const deduped = dedupeLinks(links);
    const invalid = deduped.filter((link) => !isSpotifyPlaylistLink(link));

    if (invalid.length > 0) {
      setInvalidLinks(invalid);
      return;
    }

    setInvalidLinks([]);
    try {
      await onSubmit(deduped);
    } catch (error) {
      console.error('Free playlist link submission failed', error);
    }
  };

  const hasErrors = invalidLinks.length > 0;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Spotify Free Playlist Links</CardTitle>
        <CardDescription>{helperText}</CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit} noValidate>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor={textareaId}>Playlist-Links</Label>
            <Textarea
              id={textareaId}
              value={value}
              placeholder={placeholder}
              onChange={(event) => setValue(event.target.value)}
              aria-invalid={hasErrors}
              aria-describedby={hasErrors ? errorId : undefined}
              className="min-h-[140px]"
            />
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Unterstützt Links wie <code>open.spotify.com/playlist/&lt;ID&gt;</code> sowie URIs im Format{' '}
              <code>spotify:playlist:&lt;ID&gt;</code>.
            </p>
          </div>
          {hasErrors ? (
            <div
              id={errorId}
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            >
              <p className="font-medium">Einige Einträge konnten nicht verarbeitet werden:</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {invalidLinks.map((link) => (
                  <li key={link}>{link}</li>
                ))}
              </ul>
              <p className="mt-2">Bitte prüfe die Links und versuche es erneut.</p>
            </div>
          ) : null}
        </CardContent>
        <CardFooter>
          <Button type="submit" disabled={isSubmitting} className="inline-flex items-center gap-2">
            {isSubmitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Speichern …
              </>
            ) : (
              'Speichern'
            )}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
};

export default FreeLinksForm;
