import { useMemo, useState } from 'react';

import StatusBadge from '../components/StatusBadge';
import SoulseekUploadList from '../components/SoulseekUploadList';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/shadcn';
import {
  getIntegrations,
  getSoulseekConfiguration,
  getSoulseekStatus,
  getSoulseekUploads,
  type IntegrationsData,
  type NormalizedSoulseekUpload,
  type SoulseekConfigurationEntry
} from '../api/services/soulseek';
import type { SoulseekConnectionStatus } from '../api/types';
import { useQuery } from '../lib/query';

interface StatusLabelMapping {
  ok?: Record<string, string>;
  degraded?: Record<string, string>;
  down?: Record<string, string>;
  other?: Record<string, string>;
}

const formatStatusLabel = (status: string, mapping: StatusLabelMapping) => {
  const normalized = status.toLowerCase();
  if (mapping.ok && normalized in mapping.ok) {
    return mapping.ok[normalized];
  }
  if (mapping.degraded && normalized in mapping.degraded) {
    return mapping.degraded[normalized];
  }
  if (mapping.down && normalized in mapping.down) {
    return mapping.down[normalized];
  }
  if (mapping.other && normalized in mapping.other) {
    return mapping.other[normalized];
  }
  return status.charAt(0).toUpperCase() + status.slice(1);
};

const formatDetailKey = (key: string) =>
  key
    .split(/\.|_|-/u)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

const formatDetailValue = (value: unknown): string => {
  if (Array.isArray(value)) {
    return value.map((item) => formatDetailValue(item)).join(', ');
  }
  if (value === null || value === undefined) {
    return '–';
  }
  if (value instanceof Date) {
    return value.toLocaleString();
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  if (typeof value === 'boolean') {
    return value ? 'Ja' : 'Nein';
  }
  return String(value);
};

const SoulseekPage = () => {
  const [showAllUploads, setShowAllUploads] = useState(false);

  const statusQuery = useQuery<{ status: SoulseekConnectionStatus }>({
    queryKey: ['soulseek', 'status'],
    queryFn: getSoulseekStatus
  });

  const integrationsQuery = useQuery<IntegrationsData>({
    queryKey: ['integrations', 'providers'],
    queryFn: getIntegrations
  });

  const configurationQuery = useQuery<SoulseekConfigurationEntry[]>({
    queryKey: ['soulseek', 'configuration'],
    queryFn: getSoulseekConfiguration
  });

  const uploadsQuery = useQuery<NormalizedSoulseekUpload[]>({
    queryKey: ['soulseek', 'uploads', showAllUploads ? 'all' : 'active'],
    queryFn: () => getSoulseekUploads({ includeAll: showAllUploads })
  });

  const connectionStatus = statusQuery.data?.status ?? 'unknown';
  const connectionLabelMap = {
    ok: 'Verbunden',
    connected: 'Verbunden',
    disconnected: 'Getrennt',
    unknown: 'Unbekannt'
  };
  const connectionStatusKey = (connectionStatus in connectionLabelMap
    ? connectionStatus
    : 'unknown') as keyof typeof connectionLabelMap;
  const connectionLabel = connectionLabelMap[connectionStatusKey];
  const connectionTone = connectionStatusKey === 'connected' ? 'positive' : connectionStatusKey === 'disconnected' ? 'danger' : 'info';

  const integrationOverview = integrationsQuery.data;

  const soulseekProvider = useMemo(() => {
    if (!integrationOverview) {
      return undefined;
    }
    return integrationOverview.providers.find((provider) =>
      provider.name.toLowerCase().includes('soulseek') || provider.name.toLowerCase().includes('slskd')
    );
  }, [integrationOverview]);

  const providerDetails = useMemo(() => {
    if (!soulseekProvider || !soulseekProvider.details) {
      return [] as Array<[string, string]>;
    }
    return Object.entries(soulseekProvider.details).map(([key, value]) => [key, formatDetailValue(value)]);
  }, [soulseekProvider]);

  const configurationEntries = configurationQuery.data ?? [];

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Soulseek</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Überblick über den slskd-Status, Konfiguration und aktive Upload-Freigaben.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Verbindung &amp; Integrationen</CardTitle>
            <CardDescription>
              Prüft die direkte Verbindung zum Soulseek-Daemon und den Integrationsstatus des Providers.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-foreground">Verbindungsstatus</h2>
              {statusQuery.isLoading ? (
                <p className="text-sm text-muted-foreground">Verbindung wird geprüft …</p>
              ) : statusQuery.isError ? (
                <div className="flex items-center justify-between gap-3 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-900/20 dark:text-rose-200">
                  <span>Der Verbindungsstatus konnte nicht abgerufen werden.</span>
                  <Button variant="outline" size="sm" onClick={() => statusQuery.refetch()}>
                    Erneut prüfen
                  </Button>
                </div>
              ) : (
                <div className="space-y-1">
                  <StatusBadge status={connectionStatus} label={connectionLabel} tone={connectionTone} />
                  <p className="text-sm text-muted-foreground">
                    {connectionStatus === 'connected'
                      ? 'Harmony kommuniziert erfolgreich mit slskd.'
                      : 'Keine bestätigte Verbindung zum Soulseek-Daemon.'}
                  </p>
                </div>
              )}
            </section>

            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-foreground">Provider-Gesundheit</h2>
              {integrationsQuery.isLoading ? (
                <p className="text-sm text-muted-foreground">Integrationsdaten werden geladen …</p>
              ) : integrationsQuery.isError ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-100">
                  Integrationsstatus konnte nicht geladen werden.
                </div>
              ) : integrationOverview ? (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-foreground">Gesamtzustand</span>
                    <StatusBadge
                      status={integrationOverview.overall}
                      label={formatStatusLabel(integrationOverview.overall, {
                        ok: { ok: 'Stabil' },
                        degraded: { degraded: 'Eingeschränkt' },
                        down: { down: 'Ausfall' },
                        other: { unknown: 'Unbekannt' }
                      })}
                    />
                  </div>
                  {soulseekProvider ? (
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-foreground">Soulseek (slskd)</span>
                        <StatusBadge
                          status={soulseekProvider.status}
                          label={formatStatusLabel(soulseekProvider.status, {
                            ok: { ok: 'Bereit' },
                            degraded: { degraded: 'Eingeschränkt' },
                            down: { down: 'Ausfall' },
                            other: { unknown: 'Unbekannt' }
                          })}
                        />
                      </div>
                      {providerDetails.length > 0 ? (
                        <dl className="grid gap-2">
                          {providerDetails.map(([key, value]) => (
                            <div key={key} className="space-y-0.5">
                              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                {formatDetailKey(key)}
                              </dt>
                              <dd className="text-sm text-foreground">{value}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : (
                        <p className="text-sm text-muted-foreground">Keine zusätzlichen Details gemeldet.</p>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Keine spezifischen Gesundheitsdaten für Soulseek verfügbar.
                    </p>
                  )}
                </div>
              ) : null}
            </section>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Konfiguration</CardTitle>
            <CardDescription>
              Zusammenfassung der wichtigsten slskd-Einstellungen inklusive Maskierung sensibler Werte.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {configurationQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Konfiguration wird geladen …</p>
            ) : configurationQuery.isError ? (
              <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-900/20 dark:text-rose-200">
                Konfiguration konnte nicht geladen werden.
              </div>
            ) : configurationEntries.length > 0 ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {configurationEntries.map((entry) => (
                  <div
                    key={entry.key}
                    className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-foreground">{entry.label}</p>
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{entry.key}</p>
                      </div>
                      <StatusBadge
                        status={entry.present ? 'configured' : 'missing'}
                        label={entry.present ? 'Hinterlegt' : 'Fehlt'}
                        tone={entry.present ? 'positive' : 'danger'}
                      />
                    </div>
                    <p className="break-words text-sm text-muted-foreground">
                      {entry.displayValue ?? 'Kein Wert hinterlegt'}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Keine slskd-spezifischen Einstellungen gefunden.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <CardTitle>Aktive Uploads</CardTitle>
            <CardDescription>Freigaben, die aktuell über den Soulseek-Daemon bereitgestellt werden.</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              aria-pressed={showAllUploads}
              onClick={() => setShowAllUploads((value) => !value)}
            >
              {showAllUploads ? 'Nur aktive Uploads anzeigen' : 'Alle Uploads anzeigen'}
            </Button>
            <Button variant="outline" size="sm" onClick={() => uploadsQuery.refetch()}>
              Aktualisieren
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <SoulseekUploadList
            uploads={uploadsQuery.data}
            isLoading={uploadsQuery.isLoading}
            isError={uploadsQuery.isError}
            onRetry={() => uploadsQuery.refetch()}
          />
        </CardContent>
      </Card>
    </section>
  );
};

export default SoulseekPage;
