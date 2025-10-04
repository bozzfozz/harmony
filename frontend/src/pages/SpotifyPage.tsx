import { useCallback, useEffect, useMemo, useRef, useState, useId } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CheckCircle2, Loader2, ShieldAlert } from 'lucide-react';

import SpotifyFreeImport from '../components/SpotifyFreeImport';
import {
  getSpotifyStatus,
  startSpotifyProOAuth,
  getSpotifyProOAuthStatus,
  refreshSpotifyProSession,
  consumeSpotifyProOAuthState
} from '../api/services/spotify';
import type {
  SpotifyStatusResponse,
  SpotifyProOAuthProfile,
  SpotifyProOAuthStatusResponse
} from '../api/types';
import { ApiError } from '../api/client';
import { useToast } from '../hooks/useToast';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from '../components/ui/shadcn';

const OAUTH_MESSAGE_TYPE = 'harmony.spotify.pro.oauth';
const OAUTH_POLL_INTERVAL_MS = 1500;

type OAuthFlowStatus = 'idle' | 'starting' | 'pending' | 'success' | 'error' | 'cancelled';

interface OAuthFlowState {
  status: OAuthFlowStatus;
  state: string | null;
  error: string | null;
  profile: SpotifyProOAuthProfile | null;
}

const SpotifyPage = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const dialogTitleId = useId();
  const [status, setStatus] = useState<SpotifyStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [oauthFlow, setOauthFlow] = useState<OAuthFlowState>({
    status: 'idle',
    state: null,
    error: null,
    profile: null
  });
  const [showSuccessDialog, setShowSuccessDialog] = useState(false);
  const [authorizeUrl, setAuthorizeUrl] = useState<string | null>(null);
  const [pendingDestination, setPendingDestination] = useState<string | null>(null);

  const oauthStateRef = useRef<string | null>(null);
  const oauthPollTimeoutRef = useRef<number | null>(null);
  const oauthPopupRef = useRef<Window | null>(null);
  const popupMonitorRef = useRef<number | null>(null);

  const clearPolling = useCallback(() => {
    if (oauthPollTimeoutRef.current !== null) {
      window.clearTimeout(oauthPollTimeoutRef.current);
      oauthPollTimeoutRef.current = null;
    }
    if (popupMonitorRef.current !== null) {
      window.clearInterval(popupMonitorRef.current);
      popupMonitorRef.current = null;
    }
  }, []);

  const stopOAuthFlow = useCallback(() => {
    clearPolling();
    if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
      oauthPopupRef.current.close();
    }
    oauthPopupRef.current = null;
    oauthStateRef.current = null;
    setAuthorizeUrl(null);
  }, [clearPolling]);

  const fetchStatus = useCallback(
    async (silent = false) => {
      if (!silent) {
        setIsLoading(true);
      }
      try {
        const response = await getSpotifyStatus();
        setStatus(response);
        return response;
      } catch (error) {
        const message = error instanceof ApiError ? error.message : 'Status konnte nicht geladen werden.';
        toast({ title: 'Spotify-Status', description: message, variant: 'destructive' });
        throw error;
      } finally {
        if (!silent) {
          setIsLoading(false);
        }
      }
    },
    [toast]
  );

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  useEffect(
    () => () => {
      stopOAuthFlow();
    },
    [stopOAuthFlow]
  );

  const refreshAfterSuccess = useCallback(async () => {
    try {
      const refreshed = await refreshSpotifyProSession();
      setStatus(refreshed);
    } catch (error) {
      console.warn('Failed to refresh Spotify session after OAuth', error);
      try {
        await fetchStatus(true);
      } catch (statusError) {
        console.error('Failed to reload Spotify status after OAuth', statusError);
        toast({
          title: 'Spotify-Status',
          description: 'Status konnte nach dem Login nicht aktualisiert werden. Bitte lade die Seite neu.',
          variant: 'destructive'
        });
      }
    }
  }, [fetchStatus, toast]);

  const handleOAuthError = useCallback(
    (message: string) => {
      const currentState = oauthStateRef.current;
      stopOAuthFlow();
      if (currentState) {
        consumeSpotifyProOAuthState(currentState);
      }
      setOauthFlow({ status: 'error', state: null, error: message, profile: null });
      toast({
        title: 'Spotify OAuth fehlgeschlagen',
        description: message,
        variant: 'destructive'
      });
    },
    [stopOAuthFlow, toast]
  );

  const handleOAuthCancelled = useCallback(() => {
    const currentState = oauthStateRef.current;
    stopOAuthFlow();
    if (currentState) {
      consumeSpotifyProOAuthState(currentState);
    }
    setOauthFlow({ status: 'cancelled', state: null, error: null, profile: null });
    toast({
      title: 'Spotify OAuth abgebrochen',
      description: 'Der Anmeldevorgang wurde nicht abgeschlossen.',
      variant: 'info'
    });
  }, [stopOAuthFlow, toast]);

  const handleOAuthSuccess = useCallback(
    async (payload: SpotifyProOAuthStatusResponse) => {
      const currentState = oauthStateRef.current ?? payload.state;
      stopOAuthFlow();
      if (currentState) {
        consumeSpotifyProOAuthState(currentState);
      }
      setOauthFlow({
        status: 'success',
        state: null,
        error: null,
        profile: payload.profile ?? null
      });
      setShowSuccessDialog(true);
      await refreshAfterSuccess();
    },
    [refreshAfterSuccess, stopOAuthFlow]
  );

  const processOAuthStatus = useCallback(
    async (response: SpotifyProOAuthStatusResponse) => {
      if (!response) {
        return;
      }
      const currentState = oauthStateRef.current;
      if (currentState && response.state !== currentState) {
        return;
      }
      if (response.status === 'authorized' && response.authenticated) {
        await handleOAuthSuccess(response);
        return;
      }
      if (response.status === 'failed') {
        handleOAuthError(response.error ?? 'Der OAuth-Vorgang ist fehlgeschlagen.');
        return;
      }
      if (response.status === 'cancelled') {
        handleOAuthCancelled();
      }
    },
    [handleOAuthCancelled, handleOAuthError, handleOAuthSuccess]
  );

  const pollStatus = useCallback(
    async (state: string) => {
      try {
        const response = await getSpotifyProOAuthStatus(state);
        if (response.status === 'pending' || (response.status === 'authorized' && !response.authenticated)) {
          if (oauthPollTimeoutRef.current !== null) {
            window.clearTimeout(oauthPollTimeoutRef.current);
          }
          oauthPollTimeoutRef.current = window.setTimeout(() => {
            void pollStatus(state);
          }, OAUTH_POLL_INTERVAL_MS);
          return;
        }
        await processOAuthStatus(response);
      } catch (error) {
        const message = error instanceof ApiError ? error.message : 'Status konnte nicht geladen werden.';
        handleOAuthError(message);
      }
    },
    [handleOAuthError, processOAuthStatus]
  );

  const handleStartOAuthFlow = useCallback(async () => {
    if (oauthFlow.status === 'starting' || oauthFlow.status === 'pending') {
      return;
    }
    setOauthFlow({ status: 'starting', state: null, error: null, profile: null });
    try {
      const startResponse = await startSpotifyProOAuth();
      oauthStateRef.current = startResponse.state;
      setOauthFlow({ status: 'pending', state: startResponse.state, error: null, profile: null });
      setAuthorizeUrl(startResponse.authorization_url);
      const popup = window.open(
        startResponse.authorization_url,
        'harmony_spotify_oauth',
        'width=480,height=720,noopener'
      );
      if (popup) {
        oauthPopupRef.current = popup;
        if (typeof popup.focus === 'function') {
          popup.focus();
        }
        popupMonitorRef.current = window.setInterval(() => {
          if (!oauthPopupRef.current || oauthPopupRef.current.closed) {
            clearPolling();
            popupMonitorRef.current = null;
            if (oauthStateRef.current) {
              handleOAuthCancelled();
            }
          }
        }, 1000);
      } else {
        toast({
          title: 'Fenster blockiert',
          description: 'Bitte erlaube Pop-ups für Harmony oder nutze den manuellen Link.',
          variant: 'info'
        });
      }
      void pollStatus(startResponse.state);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'OAuth-Start fehlgeschlagen.';
      handleOAuthError(message);
    }
  }, [clearPolling, handleOAuthCancelled, handleOAuthError, oauthFlow.status, pollStatus, toast]);

  const handleCancelOAuth = useCallback(() => {
    if (oauthFlow.status === 'starting' || oauthFlow.status === 'pending') {
      handleOAuthCancelled();
    }
  }, [handleOAuthCancelled, oauthFlow.status]);

  const handleCloseSuccessDialog = () => {
    setShowSuccessDialog(false);
    setOauthFlow({ status: 'idle', state: null, error: null, profile: null });
    setPendingDestination(null);
  };

  const handleNavigate = (path: string) => {
    navigate(path);
  };

  const handleProNavigate = (path: string) => {
    if (status?.authenticated) {
      navigate(path);
      return;
    }
    setPendingDestination(path);
    void handleStartOAuthFlow();
  };

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (!event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { source?: string; state?: unknown };
      if (payload.source !== OAUTH_MESSAGE_TYPE) {
        return;
      }
      const stateValue = typeof payload.state === 'string' ? payload.state : oauthStateRef.current;
      if (!stateValue) {
        return;
      }
      void pollStatus(stateValue);
    };
    window.addEventListener('message', handleMessage);
    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [pollStatus]);

  const isOAuthBusy = oauthFlow.status === 'starting' || oauthFlow.status === 'pending';
  const proDisabled = !status?.pro_available || isOAuthBusy;

  const proActionHint = useMemo(() => {
    if (!status) {
      return null;
    }
    if (!status.pro_available) {
      return 'Spotify-Credentials fehlen oder sind ungültig. Hinterlege Client-ID, Client-Secret und Redirect-URI in den Einstellungen, um PRO-Funktionen zu aktivieren.';
    }
    if (isOAuthBusy) {
      return 'OAuth-Anmeldung läuft. Schließe den Vorgang im neuen Fenster ab oder nutze den manuellen Link.';
    }
    if (!status.authenticated) {
      return 'Die Spotify-Credentials sind vorhanden. Starte einen OAuth-Login im Harmony-Backend, um PRO-Funktionen zu nutzen.';
    }
    return null;
  }, [isOAuthBusy, status]);

  const renderProButtonLabel = (label: string) =>
    isOAuthBusy ? (
      <span className="inline-flex items-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {label}
      </span>
    ) : (
      label
    );

  const successProfileName = oauthFlow.profile?.display_name ?? oauthFlow.profile?.id ?? 'Spotify Nutzer:in';

  return (
    <>
      {showSuccessDialog ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={dialogTitleId}
            className="w-full max-w-xl"
          >
            <Card className="shadow-xl">
              <CardHeader>
                <CardTitle id={dialogTitleId}>Spotify PRO verbunden</CardTitle>
                <CardDescription>
                  Willkommen, {successProfileName}! Harmony kann jetzt direkt mit deiner Spotify-Bibliothek arbeiten.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-300">
                  <CheckCircle2 className="h-5 w-5 text-emerald-500" aria-hidden />
                  <span>
                    Du kannst dieses Fenster schließen oder direkt mit den PRO-Features weiterarbeiten.
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Button
                    type="button"
                    asChild
                    variant={pendingDestination === '/library?tab=watchlist' ? 'default' : 'secondary'}
                  >
                    <Link to="/library?tab=watchlist" onClick={handleCloseSuccessDialog}>
                      Watchlist öffnen
                    </Link>
                  </Button>
                  <Button
                    type="button"
                    asChild
                    variant={pendingDestination === '/library?tab=artists' ? 'default' : 'secondary'}
                  >
                    <Link to="/library?tab=artists" onClick={handleCloseSuccessDialog}>
                      Künstlerbibliothek
                    </Link>
                  </Button>
                  <Button
                    type="button"
                    asChild
                    variant={pendingDestination === '/library?tab=downloads' ? 'default' : 'secondary'}
                  >
                    <Link to="/library?tab=downloads" onClick={handleCloseSuccessDialog}>
                      Backfill-Aufträge
                    </Link>
                  </Button>
                </div>
              </CardContent>
              <CardFooter className="justify-end">
                <Button type="button" variant="ghost" onClick={handleCloseSuccessDialog}>
                  Schließen
                </Button>
              </CardFooter>
            </Card>
          </div>
        </div>
      ) : null}
      <div className="space-y-6">
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Spotify Status</CardTitle>
            <CardDescription>
              Überblick über die verfügbaren Spotify-Funktionen und die OAuth-Anbindung.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                Lade Status …
              </div>
            ) : status ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <ShieldAlert className="h-5 w-5 text-indigo-600" />
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                      Verbindungsstatus:{' '}
                      {status.status === 'connected'
                        ? 'Verbunden'
                        : status.status === 'unauthenticated'
                          ? 'Nicht authentifiziert'
                          : 'Nicht konfiguriert'}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {status.free_available
                        ? 'FREE-Import steht bereit und nutzt Soulseek für die Downloads.'
                        : 'FREE-Import ist derzeit nicht verfügbar. Prüfe Worker-Status und Soulseek-Verbindung.'}
                    </p>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
                    <p className="font-medium text-slate-900 dark:text-slate-100">FREE verfügbar</p>
                    <p className="text-slate-600 dark:text-slate-400">
                      {status.free_available
                        ? 'Ja – Worker aktiv und Soulseek erreichbar.'
                        : 'Nein – bitte Worker-Status und Soulseek prüfen.'}
                    </p>
                  </div>
                  <div className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
                    <p className="font-medium text-slate-900 dark:text-slate-100">PRO verfügbar</p>
                    <p className="text-slate-600 dark:text-slate-400">
                      {status.pro_available ? 'Ja – OAuth-Credentials gesetzt.' : 'Nein – Zugangsdaten fehlen.'}
                    </p>
                  </div>
                  <div className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
                    <p className="font-medium text-slate-900 dark:text-slate-100">Authentifiziert</p>
                    <p className="text-slate-600 dark:text-slate-400">
                      {status.authenticated ? 'Aktive Session vorhanden.' : 'Noch kein Login durchgeführt.'}
                    </p>
                  </div>
                </div>
                {proActionHint ? (
                  <p className="text-sm text-amber-600 dark:text-amber-400">{proActionHint}</p>
                ) : null}
                {!status.free_available ? (
                  <p className="text-sm text-amber-600 dark:text-amber-400">
                    Der FREE-Import ist deaktiviert. Prüfe die Soulseek-Konfiguration und starte den Import-Worker neu.
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-slate-600 dark:text-slate-400">Statusinformationen sind derzeit nicht verfügbar.</p>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Spotify PRO Aktionen</CardTitle>
            <CardDescription>
              Nutze die integrierten Spotify-APIs für automatische Bibliotheks-Synchronisation und Kurations-Workflows.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-slate-600 dark:text-slate-300">
              PRO-Funktionen greifen auf die Spotify-API zu. Ohne gültige Credentials bleiben die Aktionen deaktiviert.
              Nach erfolgreicher Authentifizierung stehen Watchlist, Artist-Importe und Backfill-Aufträge bereit.
            </p>
            {(oauthFlow.status === 'starting' || oauthFlow.status === 'pending') && (
              <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-800 dark:bg-slate-900/40">
                <div className="flex items-start gap-3">
                  <Loader2 className="h-4 w-4 flex-none animate-spin text-indigo-600" aria-hidden />
                  <div className="space-y-1">
                    <p className="font-medium text-slate-900 dark:text-slate-100">Spotify OAuth läuft …</p>
                    <p className="text-xs text-slate-600 dark:text-slate-400">
                      Schließe die Anmeldung im geöffneten Fenster ab. Falls kein Fenster erschienen ist, kannst du den OAuth-Dialog hier erneut öffnen.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {authorizeUrl ? (
                        <Button type="button" variant="link" className="px-0" asChild>
                          <a href={authorizeUrl} target="_blank" rel="noreferrer noopener">
                            OAuth manuell öffnen
                          </a>
                        </Button>
                      ) : null}
                      <Button type="button" size="sm" variant="ghost" onClick={handleCancelOAuth}>
                        Abbrechen
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )}
            {oauthFlow.status === 'error' && oauthFlow.error ? (
              <p className="text-sm text-amber-600 dark:text-amber-400">{oauthFlow.error}</p>
            ) : null}
            {oauthFlow.status === 'cancelled' ? (
              <p className="text-sm text-muted-foreground">
                OAuth wurde abgebrochen. Du kannst den Vorgang jederzeit erneut starten.
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={() => handleProNavigate('/library?tab=watchlist')}
                disabled={proDisabled}
              >
                {renderProButtonLabel('Watchlist öffnen')}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => handleProNavigate('/library?tab=artists')}
                disabled={proDisabled}
              >
                {renderProButtonLabel('Künstlerbibliothek')}
              </Button>
              <Button type="button" variant="outline" onClick={() => handleNavigate('/settings')}>
                Einstellungen
              </Button>
            </div>
          </CardContent>
          {proActionHint ? (
            <CardFooter>
              <p className="text-xs text-amber-600 dark:text-amber-400">{proActionHint}</p>
            </CardFooter>
          ) : null}
        </Card>

        <SpotifyFreeImport />
      </div>
    </>
  );
};

export default SpotifyPage;
