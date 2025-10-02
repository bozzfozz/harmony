import { useState } from 'react';

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/shadcn';
import { useToast } from '../../hooks/useToast';
import { ApiError } from '../../api/client';
import { validateSecret } from '../../api/services/system';
import type { SecretProvider, SecretValidationData } from '../../api/types';

const PROVIDERS: { id: SecretProvider; label: string; description: string }[] = [
  {
    id: 'slskd_api_key',
    label: 'Soulseek API-Key',
    description: 'Validiert via slskd `/api/v2/me` mit hartem Timeout.'
  },
  {
    id: 'spotify_client_secret',
    label: 'Spotify Client Secret',
    description: 'Verwendet den Client-Credentials-Flow zum Live-Ping.'
  }
];

type ValidationState = Record<SecretProvider, SecretValidationData | null>;
type LoadingState = Record<SecretProvider, boolean>;

interface DisplayStatus {
  label: string;
  tone: string;
  timestamp?: string;
  mode?: string;
  reason?: string;
  note?: string;
  description?: string;
}

const INITIAL_STATE = PROVIDERS.reduce<ValidationState>((accumulator, provider) => {
  accumulator[provider.id] = null;
  return accumulator;
}, {} as ValidationState);

const INITIAL_LOADING = PROVIDERS.reduce<LoadingState>((accumulator, provider) => {
  accumulator[provider.id] = false;
  return accumulator;
}, {} as LoadingState);

const modeLabel = (mode: SecretValidationData['validated']['mode']) =>
  mode === 'live' ? 'Live-Check' : 'Formatprüfung';

const SecretsPanel = () => {
  const { toast } = useToast();
  const [results, setResults] = useState<ValidationState>(INITIAL_STATE);
  const [loading, setLoading] = useState<LoadingState>(INITIAL_LOADING);

  const resolveStatus = (entry: SecretValidationData | null): DisplayStatus => {
    if (!entry) {
      return {
        label: 'Noch nicht geprüft',
        tone: 'text-muted-foreground',
        description: 'Nutze „Jetzt testen“, um eine Validierung zu starten.'
      } as const;
    }
    const { validated } = entry;
    const base = {
      timestamp: new Date(validated.at).toLocaleString(),
      mode: modeLabel(validated.mode),
      reason: validated.reason,
      note: validated.note
    };
    if (!validated.valid) {
      return {
        ...base,
        label: 'Ungültig',
        tone: 'text-rose-600 dark:text-rose-400'
      };
    }
    if (validated.mode === 'format' && validated.note) {
      return {
        ...base,
        label: 'Unbekannt',
        tone: 'text-amber-600 dark:text-amber-400'
      };
    }
    return {
      ...base,
      label: 'Gültig',
      tone: 'text-emerald-600 dark:text-emerald-400'
    };
  };

  const handleValidate = async (provider: SecretProvider) => {
    setLoading((previous) => ({ ...previous, [provider]: true }));
    try {
      const response = await validateSecret(provider);
      if (!response.ok || !response.data) {
        throw new Error('Validierung konnte nicht abgeschlossen werden.');
      }
      setResults((previous) => ({ ...previous, [provider]: response.data }));
    } catch (error) {
      let description = 'Validierung konnte nicht durchgeführt werden.';
      if (error instanceof ApiError) {
        description = error.message;
        if (!error.handled) {
          error.markHandled();
        }
      }
      toast({
        title: 'Secret-Validierung fehlgeschlagen',
        description,
        variant: 'destructive'
      });
    } finally {
      setLoading((previous) => ({ ...previous, [provider]: false }));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Secret-Validierung</CardTitle>
        <CardDescription>
          Prüfe slskd- und Spotify-Credentials ohne Secret-Rückgabe. Bei Timeouts erfolgt ein Format-Check mit Hinweis.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {PROVIDERS.map((provider) => {
          const result = results[provider.id];
          const status = resolveStatus(result);
          return (
            <div key={provider.id} className="flex flex-col gap-3 rounded-lg border border-border p-4 md:flex-row md:items-start md:justify-between md:gap-6">
              <div className="space-y-2">
                <div>
                  <p className="text-sm font-medium leading-none">{provider.label}</p>
                  <p className="text-xs text-muted-foreground">{provider.description}</p>
                </div>
                <div className="space-y-1">
                  <p className={`text-sm font-semibold ${status.tone}`}>{status.label}</p>
                  {status.timestamp ? (
                    <p className="text-xs text-muted-foreground">Zuletzt geprüft: {status.timestamp}</p>
                  ) : null}
                  {status.mode ? (
                    <p className="text-xs text-muted-foreground">Modus: {status.mode}</p>
                  ) : null}
                  {status.reason ? (
                    <p className="text-xs text-muted-foreground">Grund: {status.reason}</p>
                  ) : null}
                  {status.note ? (
                    <p className="text-xs text-muted-foreground">Hinweis: {status.note}</p>
                  ) : null}
                  {!result ? (
                    <p className="text-xs text-muted-foreground">{status.description}</p>
                  ) : null}
                </div>
              </div>
              <div className="flex items-center justify-end md:justify-start">
                <Button onClick={() => handleValidate(provider.id)} disabled={loading[provider.id]}>
                  {loading[provider.id] ? 'Prüfe …' : 'Jetzt testen'}
                </Button>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
};

export default SecretsPanel;

