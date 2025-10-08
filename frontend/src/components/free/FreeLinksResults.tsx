import { useMemo } from 'react';

import type {
  FreePlaylistLinkAccepted,
  FreePlaylistLinkSkipped
} from '../../lib/api/freeLinks';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '../ui/shadcn';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';

const formatTimestamp = (timestamp: Date | null): string => {
  if (!timestamp) {
    return 'Noch keine Speicherung durchgeführt';
  }
  try {
    return new Intl.DateTimeFormat('de-DE', {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(timestamp);
  } catch (error) {
    console.warn('Failed to format timestamp', error);
    return timestamp.toISOString();
  }
};

const shortenUrl = (url: string): string => {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`;
  } catch (error) {
    return url;
  }
};

const REASON_LABELS: Record<string, string> = {
  duplicate: 'Bereits vorhanden',
  invalid: 'Ungültig',
  non_playlist: 'Kein Playlist-Link'
};

const mapReason = (reason: string): string => REASON_LABELS[reason] ?? reason;

export interface FreeLinksResultsProps {
  accepted: FreePlaylistLinkAccepted[];
  skipped: FreePlaylistLinkSkipped[];
  lastSavedAt: Date | null;
}

const FreeLinksResults = ({ accepted, skipped, lastSavedAt }: FreeLinksResultsProps) => {
  const lastSavedLabel = useMemo(() => formatTimestamp(lastSavedAt), [lastSavedAt]);
  const hasResults = accepted.length > 0 || skipped.length > 0;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Zuletzt gespeichert</CardTitle>
        <CardDescription>{lastSavedLabel}</CardDescription>
      </CardHeader>
      <CardContent>
        {hasResults ? (
          <Accordion type="multiple" defaultValue={accepted.length > 0 ? ['accepted'] : ['skipped']}>
            <AccordionItem value="accepted">
              <AccordionTrigger>Erfolgreich übernommen ({accepted.length})</AccordionTrigger>
              <AccordionContent>
                {accepted.length > 0 ? (
                  <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Playlist-ID</TableHead>
                          <TableHead>Quelle</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {accepted.map((entry) => (
                          <TableRow key={entry.playlist_id}>
                            <TableCell className="font-mono text-sm">{entry.playlist_id}</TableCell>
                            <TableCell>
                              <a
                                href={entry.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-primary underline-offset-2 hover:underline"
                              >
                                {shortenUrl(entry.url)}
                              </a>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">Noch keine Links akzeptiert.</p>
                )}
              </AccordionContent>
            </AccordionItem>
            <AccordionItem value="skipped">
              <AccordionTrigger>Übersprungen ({skipped.length})</AccordionTrigger>
              <AccordionContent>
                {skipped.length > 0 ? (
                  <ul className="space-y-3">
                    {skipped.map((entry) => (
                      <li key={`${entry.url}-${entry.reason}`} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="truncate text-sm font-medium" title={entry.url}>
                            {entry.url}
                          </span>
                          <Badge variant="warning">{mapReason(entry.reason)}</Badge>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">Keine übersprungenen Einträge.</p>
                )}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        ) : (
          <p className="text-sm text-muted-foreground">
            Noch keine Ergebnisse. Speichere Spotify-Playlist-Links, um hier den Status zu sehen.
          </p>
        )}
      </CardContent>
    </Card>
  );
};

export default FreeLinksResults;
