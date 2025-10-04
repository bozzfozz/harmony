import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, ShieldAlert } from 'lucide-react';

import SpotifyFreeImport from '../components/SpotifyFreeImport';
import { getSpotifyStatus } from '../api/services/spotify';
import type { SpotifyStatusResponse } from '../api/types';
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

const SpotifyPage = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [status, setStatus] = useState<SpotifyStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await getSpotifyStatus();
        setStatus(response);
      } catch (error) {
        const message = error instanceof ApiError ? error.message : 'Status konnte nicht geladen werden.';
        toast({ title: 'Spotify-Status', description: message, variant: 'destructive' });
      } finally {
        setIsLoading(false);
      }
    };
    fetchStatus();
  }, [toast]);

  const proDisabled = !status?.pro_available;
  const proActionHint = useMemo(() => {
    if (!status) {
      return null;
    }
    if (!status.pro_available) {
      return 'Spotify-Credentials fehlen oder sind ungültig. Hinterlege Client-ID, Client-Secret und Redirect-URI in den Einstellungen, um PRO-Funktionen zu aktivieren.';
    }
    if (!status.authenticated) {
      return 'Die Spotify-Credentials sind vorhanden. Starte einen OAuth-Login im Harmony-Backend, um PRO-Funktionen zu nutzen.';
    }
    return null;
  }, [status]);

  const handleNavigate = (path: string) => {
    navigate(path);
  };

  return (
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
                    Verbindungsstatus: {status.status === 'connected' ? 'Verbunden' : status.status === 'unauthenticated' ? 'Nicht authentifiziert' : 'Nicht konfiguriert'}
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
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => handleNavigate('/library?tab=watchlist')} disabled={proDisabled}>
              Watchlist öffnen
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => handleNavigate('/library?tab=artists')}
              disabled={proDisabled}
            >
              Künstlerbibliothek
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
  );
};

export default SpotifyPage;
