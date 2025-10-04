import { useEffect, useState } from 'react';
import { Loader2, ShieldAlert } from 'lucide-react';

import SpotifyFreeImport from '../components/SpotifyFreeImport';
import { getSpotifyStatus } from '../api/services/spotify';
import type { SpotifyStatusResponse } from '../api/types';
import { ApiError } from '../api/client';
import { useToast } from '../hooks/useToast';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '../components/ui/shadcn';

const SpotifyPage = () => {
  const { toast } = useToast();
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
                    FREE-Import ist immer verfügbar. PRO-Funktionen erfordern gültige Spotify-Credentials.
                  </p>
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
                  <p className="font-medium text-slate-900 dark:text-slate-100">PRO verfügbar</p>
                  <p className="text-slate-600 dark:text-slate-400">{status.pro_available ? 'Ja – OAuth-Credentials gesetzt.' : 'Nein – Zugangsdaten fehlen.'}</p>
                </div>
                <div className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
                  <p className="font-medium text-slate-900 dark:text-slate-100">Authentifiziert</p>
                  <p className="text-slate-600 dark:text-slate-400">{status.authenticated ? 'Aktive Session vorhanden.' : 'Noch kein Login durchgeführt.'}</p>
                </div>
              </div>
              {!status.pro_available && (
                <p className="text-sm text-amber-600 dark:text-amber-400">
                  Spotify-Credentials fehlen oder sind ungültig. Hinterlegen Sie Client-ID, Client-Secret und Redirect-URI in den Einstellungen,
                  um PRO-Funktionen zu aktivieren.
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-600 dark:text-slate-400">Statusinformationen sind derzeit nicht verfügbar.</p>
          )}
        </CardContent>
      </Card>

      <SpotifyFreeImport proAvailable={status?.pro_available ?? false} />
    </div>
  );
};

export default SpotifyPage;
