import { useCallback, useState } from 'react';

import { ApiError } from '../../api/client';
import FreeLinksForm from '../../components/free/FreeLinksForm';
import FreeLinksResults from '../../components/free/FreeLinksResults';
import { useToast } from '../../hooks/useToast';
import {
  FreePlaylistLinkAccepted,
  FreePlaylistLinkSkipped,
  postFreePlaylistLinks
} from '../../lib/api/freeLinks';

const trackUxEvent = (name: string, payload?: Record<string, unknown>) => {
  if (typeof console === 'undefined' || typeof console.info !== 'function') {
    return;
  }
  if (payload) {
    console.info(`[ux] ${name}`, payload);
  } else {
    console.info(`[ux] ${name}`);
  }
};

const FreeLinksPage = () => {
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [accepted, setAccepted] = useState<FreePlaylistLinkAccepted[]>([]);
  const [skipped, setSkipped] = useState<FreePlaylistLinkSkipped[]>([]);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);

  const handleSubmit = useCallback(
    async (links: string[]) => {
      if (links.length === 0) {
        return;
      }
      trackUxEvent('ux.free_links.submit', { count: links.length });
      setIsSubmitting(true);
      try {
        const payload = links.length === 1 ? { url: links[0] } : { urls: links };
        const response = await postFreePlaylistLinks(payload);
        const timestamp = new Date();
        setAccepted(response.accepted);
        setSkipped(response.skipped);
        setLastSavedAt(timestamp);
        const description = `Akzeptiert: ${response.accepted.length}. Übersprungen: ${response.skipped.length}.`;
        toast({ title: 'Playlist-Links gespeichert', description });
        trackUxEvent('ux.free_links.success', {
          accepted: response.accepted.length,
          skipped: response.skipped.length
        });
      } catch (error) {
        const message =
          error instanceof ApiError
            ? error.message
            : 'Die Playlist-Links konnten nicht gespeichert werden.';
        toast({ title: 'Speichern fehlgeschlagen', description: message, variant: 'destructive' });
        trackUxEvent('ux.free_links.error', {
          message,
          status: error instanceof ApiError ? error.status : undefined
        });
      } finally {
        setIsSubmitting(false);
      }
    },
    [toast]
  );

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Free Playlist Links</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Speichere einzelne oder mehrere Spotify-Playlist-Links und lasse sie direkt von der Free-Ingest-Pipeline verarbeiten.
        </p>
      </section>
      <FreeLinksForm onSubmit={handleSubmit} isSubmitting={isSubmitting} />
      <FreeLinksResults accepted={accepted} skipped={skipped} lastSavedAt={lastSavedAt} />
    </div>
  );
};

export default FreeLinksPage;
