import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';

import { consumeSpotifyProOAuthState } from '../api/services/spotify';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '../components/ui/shadcn';

const CALLBACK_MESSAGE_TYPE = 'harmony.spotify.pro.oauth';

type CallbackStatus = 'pending' | 'authorized' | 'failed';

const SpotifyProOAuthCallbackPage = () => {
  const [status, setStatus] = useState<CallbackStatus>('pending');
  const [details, setDetails] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const state = params.get('state');
    const error = params.get('error');
    const errorDescription = params.get('error_description');
    const message = errorDescription ?? error ?? null;
    const normalizedStatus: CallbackStatus = error ? 'failed' : 'authorized';

    if (state) {
      consumeSpotifyProOAuthState(state);
    }

    if (window.opener && !window.opener.closed) {
      try {
        window.opener.postMessage(
          {
            source: CALLBACK_MESSAGE_TYPE,
            state: state ?? undefined,
            status: normalizedStatus,
            error: message ?? undefined
          },
          window.location.origin
        );
      } catch (postMessageError) {
        console.warn('Unable to notify opener about Spotify OAuth callback', postMessageError);
      }
    }

    setStatus(normalizedStatus);
    setDetails(message);

    if (!error) {
      const timer = window.setTimeout(() => {
        window.close();
      }, 2000);
      return () => {
        window.clearTimeout(timer);
      };
    }
    return undefined;
  }, []);

  const statusCopy = useMemo(() => {
    if (status === 'authorized') {
      return {
        title: 'Spotify-Anmeldung abgeschlossen',
        description: 'Du kannst dieses Fenster schließen. Harmony verarbeitet den Login automatisch.'
      };
    }
    if (status === 'failed') {
      return {
        title: 'Spotify-Anmeldung fehlgeschlagen',
        description: details ?? 'Bitte versuche es erneut oder prüfe die Anmeldedaten.'
      };
    }
    return {
      title: 'Spotify-Anmeldung wird verarbeitet …',
      description: 'Bitte warte einen Moment. Dieses Fenster schließt sich gleich automatisch.'
    };
  }, [details, status]);

  const renderIcon = () => {
    if (status === 'authorized') {
      return <CheckCircle2 className="h-6 w-6 text-emerald-500" aria-hidden />;
    }
    if (status === 'failed') {
      return <XCircle className="h-6 w-6 text-red-500" aria-hidden />;
    }
    return <Loader2 className="h-6 w-6 animate-spin text-indigo-600" aria-hidden />;
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-6 dark:bg-slate-950">
      <Card className="w-full max-w-lg shadow-lg">
        <CardHeader>
          <CardTitle>Spotify OAuth Callback</CardTitle>
          <CardDescription>Dieses Fenster informiert dich über den Status der Anmeldung.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start gap-3">
            {renderIcon()}
            <div className="space-y-1">
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{statusCopy.title}</p>
              <p className="text-sm text-slate-600 dark:text-slate-400">{statusCopy.description}</p>
            </div>
          </div>
          {details && status === 'failed' ? (
            <pre className="rounded-md bg-red-50 p-3 text-xs text-red-700 dark:bg-red-950 dark:text-red-200">
              {details}
            </pre>
          ) : null}
          <div className="flex justify-end">
            <Button type="button" variant="secondary" onClick={() => window.close()}>
              Fenster schließen
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default SpotifyProOAuthCallbackPage;
