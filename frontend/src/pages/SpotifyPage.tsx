import { useEffect, useState } from 'react';
import { Loader2, ShieldCheck } from 'lucide-react';

import SpotifyFreeImport from '../components/SpotifyFreeImport';
import {
  getSpotifyMode,
  setSpotifyMode,
  SpotifyMode
} from '../lib/api';
import { ApiError } from '../lib/api';
import { useToast } from '../hooks/useToast';
import { Button } from '../components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '../components/ui/card';

const SpotifyPage = () => {
  const { toast } = useToast();
  const [mode, setMode] = useState<SpotifyMode>('PRO');
  const [isLoading, setIsLoading] = useState(true);
  const [isUpdating, setIsUpdating] = useState(false);

  useEffect(() => {
    const fetchMode = async () => {
      try {
        const response = await getSpotifyMode();
        setMode(response.mode);
      } catch (error) {
        const message = error instanceof ApiError ? error.message : 'Modus konnte nicht geladen werden.';
        toast({ title: 'Spotify-Modus', description: message, variant: 'destructive' });
      } finally {
        setIsLoading(false);
      }
    };
    fetchMode();
  }, [toast]);

  const handleModeChange = async (targetMode: SpotifyMode) => {
    if (targetMode === mode) {
      return;
    }
    setIsUpdating(true);
    try {
      await setSpotifyMode(targetMode);
      setMode(targetMode);
      toast({
        title: 'Modus aktualisiert',
        description: targetMode === 'FREE' ? 'Spotify FREE aktiviert.' : 'Spotify PRO reaktiviert.'
      });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Moduswechsel fehlgeschlagen.';
      toast({ title: 'Moduswechsel', description: message, variant: 'destructive' });
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Spotify Modus</CardTitle>
          <CardDescription>
            Wähle zwischen voll integrierter PRO-Anbindung und dem schlanken FREE-Modus ohne OAuth.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              Lade aktuellen Modus …
            </div>
          ) : (
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <ShieldCheck className="h-5 w-5 text-indigo-600" />
                <div>
                  <p className="text-sm font-medium text-slate-900 dark:text-slate-100">Aktueller Modus: {mode}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    PRO nutzt die Spotify-API inklusive OAuth. FREE arbeitet vollständig nutzereingabebasiert.
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={mode === 'FREE' ? 'default' : 'outline'}
                  disabled={isUpdating}
                  onClick={() => handleModeChange('FREE')}
                >
                  Spotify FREE
                </Button>
                <Button
                  type="button"
                  variant={mode === 'PRO' ? 'default' : 'outline'}
                  disabled={isUpdating}
                  onClick={() => handleModeChange('PRO')}
                >
                  Spotify PRO
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <SpotifyFreeImport mode={mode} />
    </div>
  );
};

export default SpotifyPage;
