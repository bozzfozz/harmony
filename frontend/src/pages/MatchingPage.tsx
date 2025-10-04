import { Loader2, RefreshCcw } from 'lucide-react';

import MetricCard, { type MetricTone } from '../components/MetricCard';
import StatusBadge from '../components/StatusBadge';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/shadcn';
import { getMatchingOverview, type MatchingOverview } from '../api/services/matching';
import { useToast } from '../hooks/useToast';
import { useQuery } from '../lib/query';
import { formatLastSeen, formatQueueSize, formatStatus } from '../components/WorkerHealthCard';

const alertToneClasses = {
  danger:
    'rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-900/30 dark:text-rose-100',
  warning:
    'rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100',
  info:
    'rounded-md border border-slate-200 bg-slate-100/60 p-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200'
} as const;

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'short',
  timeStyle: 'short'
});

const numberFormatter = new Intl.NumberFormat();

const formatEventTimestamp = (value?: string) => {
  if (!value) {
    return 'Zeitpunkt unbekannt';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return 'Zeitpunkt unbekannt';
  }
  return dateFormatter.format(parsed);
};

const formatConfidenceDisplay = (value?: number | null) => {
  if (typeof value !== 'number') {
    return '—';
  }
  return `${(value * 100).toFixed(1)} %`;
};

const determineConfidenceTone = (value?: number | null): MetricTone => {
  if (typeof value !== 'number') {
    return 'info';
  }
  if (value >= 0.85) {
    return 'positive';
  }
  if (value >= 0.65) {
    return 'info';
  }
  if (value >= 0.45) {
    return 'warning';
  }
  return 'danger';
};

const determineWorkerTone = (status?: string): MetricTone => {
  if (!status) {
    return 'info';
  }
  const normalized = status.toLowerCase();
  if (normalized === 'running') {
    return 'positive';
  }
  if (['starting', 'queued'].includes(normalized)) {
    return 'info';
  }
  if (['stale', 'blocked'].includes(normalized)) {
    return 'warning';
  }
  if (['errored', 'stopped'].includes(normalized)) {
    return 'danger';
  }
  return 'info';
};

const MatchingPage = () => {
  const { toast } = useToast();

  const overviewQuery = useQuery<MatchingOverview>({
    queryKey: ['matching', 'overview'],
    queryFn: getMatchingOverview,
    refetchInterval: 20000,
    onError: (error) => {
      const description = error instanceof Error ? error.message : undefined;
      toast({
        title: 'Matching-Daten konnten nicht geladen werden',
        description,
        variant: 'destructive'
      });
    }
  });

  const { data, isLoading, isError, refetch } = overviewQuery;

  const worker = data?.worker;
  const workerStatus = worker?.status;
  const queueSize = typeof worker?.queueSize === 'number' ? worker.queueSize : 0;
  const hasQueueBacklog = typeof worker?.queueSize === 'number' && worker.queueSize > 0;
  const workerTone = determineWorkerTone(workerStatus);
  const workerStatusLabel = formatStatus(workerStatus);
  const queueDisplay = formatQueueSize(worker?.rawQueueSize ?? worker?.queueSize ?? null);

  const metrics = data?.metrics;
  const events = data?.events ?? [];

  const { message: workerWarningMessage, tone: workerWarningTone } = (() => {
    if (!workerStatus) {
      return { message: undefined, tone: 'info' as const };
    }
    const normalized = workerStatus.toLowerCase();
    if (normalized === 'stopped') {
      return {
        message:
          'Der Matching-Worker ist gestoppt. Starte den Prozess neu oder überprüfe die Supervisor-Konfiguration.',
        tone: 'danger' as const
      };
    }
    if (normalized === 'errored') {
      return {
        message: 'Der Matching-Worker meldet Fehler. Prüfe die Worker-Logs und Matching-Konfiguration.',
        tone: 'danger' as const
      };
    }
    if (normalized === 'blocked') {
      return {
        message: 'Der Matching-Worker ist blockiert. Überprüfe Queue-Jobs und Credentials, um den Blocker zu entfernen.',
        tone: 'warning' as const
      };
    }
    if (normalized === 'stale') {
      return {
        message: 'Der Matching-Worker wurde seit einiger Zeit nicht gesehen. Kontrolliere Heartbeat, Dispatcher und Worker-Logs.',
        tone: 'warning' as const
      };
    }
    return { message: undefined, tone: 'info' as const };
  })();

  const queueWarningMessage = hasQueueBacklog
    ? `Die Matching-Queue enthält ${numberFormatter.format(
        queueSize
      )} offene Jobs. Prüfe Worker-Auslastung oder Matching-Konfiguration.`
    : undefined;
  const queueWarningTone = hasQueueBacklog ? 'warning' : 'info';

  const renderState = (content: () => JSX.Element) => {
    if (isLoading) {
      return (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Daten werden geladen …
        </div>
      );
    }
    if (isError || !data) {
      return (
        <div className="space-y-3 text-sm text-muted-foreground">
          <p>Matching-Daten stehen derzeit nicht zur Verfügung.</p>
          <Button size="sm" variant="outline" onClick={() => void refetch()} className="inline-flex items-center gap-2">
            <RefreshCcw className="h-4 w-4" aria-hidden /> Erneut versuchen
          </Button>
        </div>
      );
    }
    return content();
  };

  return (
    <section className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Matching</h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Überwache den Status der Matching-Pipeline, erkenne Backlogs frühzeitig und prüfe die Qualität der gespeicherten
            Zuordnungen.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          className="inline-flex items-center gap-2"
          disabled={isLoading}
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Aktualisiere …
            </>
          ) : (
            <>
              <RefreshCcw className="h-4 w-4" aria-hidden />
              Aktualisieren
            </>
          )}
        </Button>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Worker-Status</CardTitle>
            <CardDescription>Heartbeat, Queue-Größe und letzte Aktivität des Matching-Workers.</CardDescription>
          </CardHeader>
          <CardContent>
            {renderState(() => (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-foreground">Matching-Worker</p>
                    <p className="text-xs text-muted-foreground">Persistiert bestätigte Zuordnungen.</p>
                  </div>
                  <StatusBadge status={workerStatus ?? 'unbekannt'} label={workerStatusLabel} tone={workerTone} />
                </div>
                <dl className="grid gap-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted-foreground">Queue</dt>
                    <dd className="font-semibold text-foreground">{queueDisplay}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted-foreground">Zuletzt gesehen</dt>
                    <dd className="font-semibold text-foreground">{formatLastSeen(worker?.lastSeen)}</dd>
                  </div>
                </dl>
                {workerWarningMessage ? (
                  <div className={alertToneClasses[workerWarningTone]}>{workerWarningMessage}</div>
                ) : null}
                {queueWarningMessage ? (
                  <div className={alertToneClasses[queueWarningTone]}>{queueWarningMessage}</div>
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Matching-Metriken</CardTitle>
            <CardDescription>Zuletzt gespeicherte Score-Qualität und aggregierte Speicherquoten.</CardDescription>
          </CardHeader>
          <CardContent>
            {renderState(() => {
              const averageConfidence = metrics?.lastAverageConfidence;
              const lastDiscarded = metrics?.lastDiscarded ?? null;
              const savedTotal = metrics?.savedTotal ?? null;
              const discardedTotal = metrics?.discardedTotal ?? null;

              const lastDiscardedTone: MetricTone = typeof lastDiscarded === 'number' && lastDiscarded > 0 ? 'warning' : 'info';

              return (
                <div className="grid gap-4 sm:grid-cols-2">
                  <MetricCard
                    label="Ø Konfidenz (letzte Charge)"
                    value={formatConfidenceDisplay(averageConfidence)}
                    tone={determineConfidenceTone(averageConfidence)}
                    hint={
                      typeof averageConfidence === 'number'
                        ? 'Durchschnittliche Score-Übereinstimmung der zuletzt gespeicherten Matches.'
                        : 'Noch keine Matches bewertet.'
                    }
                  />
                  <MetricCard
                    label="Verworfen in letzter Charge"
                    value={
                      typeof lastDiscarded === 'number'
                        ? numberFormatter.format(lastDiscarded)
                        : '—'
                    }
                    tone={lastDiscardedTone}
                    hint={
                      typeof lastDiscarded === 'number'
                        ? 'Matches, die aufgrund niedriger Scores oder Konflikte verworfen wurden.'
                        : 'Es liegen noch keine Verwerfungen vor.'
                    }
                  />
                  <MetricCard
                    label="Gesamt gespeichert"
                    value={typeof savedTotal === 'number' ? numberFormatter.format(savedTotal) : '—'}
                    tone="info"
                    hint={
                      typeof savedTotal === 'number'
                        ? 'Alle erfolgreich persistierten Matches seit Aktivierung der Pipeline.'
                        : 'Noch keine Matches gespeichert.'
                    }
                  />
                  <MetricCard
                    label="Gesamt verworfen"
                    value={
                      typeof discardedTotal === 'number' ? numberFormatter.format(discardedTotal) : '—'
                    }
                    tone={typeof discardedTotal === 'number' && discardedTotal > 0 ? 'warning' : 'info'}
                    hint={
                      typeof discardedTotal === 'number'
                        ? 'Summe aller verworfenen Vorschläge – beobachte Anstieg für Qualitätsprobleme.'
                        : 'Keine verworfenen Vorschläge erfasst.'
                    }
                  />
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Letzte Matching-Batches</CardTitle>
          <CardDescription>Aktivitätslog für die Speicherung oder Verwerfung ganzer Matching-Chargen.</CardDescription>
        </CardHeader>
        <CardContent>
          {renderState(() => (
            events.length > 0 ? (
              <ul className="space-y-4">
                {events.map((event) => {
                  const storedCount = typeof event.stored === 'number' ? event.stored : 0;
                  const discardedCount = typeof event.discarded === 'number' ? event.discarded : 0;
                  const average = formatConfidenceDisplay(event.averageConfidence);
                  const allDiscarded = storedCount === 0 && discardedCount > 0;
                  const mixedResult = storedCount > 0 && discardedCount > 0;
                  const badgeProps = allDiscarded
                    ? { status: 'discarded', label: 'Alles verworfen', tone: 'danger' as const }
                    : mixedResult
                    ? { status: 'partial', label: 'Teilweise gespeichert', tone: 'warning' as const }
                    : { status: 'completed', label: 'Verarbeitet', tone: 'positive' as const };

                  return (
                    <li
                      key={`${event.timestamp}-${event.jobId ?? event.jobType ?? 'batch'}`}
                      className="rounded-lg border border-slate-200 bg-white/60 p-4 dark:border-slate-700 dark:bg-slate-900/40"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-foreground">Charge vom {formatEventTimestamp(event.timestamp)}</p>
                          <p className="text-xs text-muted-foreground">
                            {event.jobType ? `Typ: ${event.jobType}` : 'Typ: matching_batch'}
                            {event.jobId ? ` · Job ${event.jobId}` : ''}
                          </p>
                        </div>
                        <StatusBadge {...badgeProps} />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted-foreground">
                        <span>
                          <span className="font-semibold text-foreground">{numberFormatter.format(storedCount)}</span> gespeichert
                        </span>
                        <span>
                          <span className="font-semibold text-foreground">{numberFormatter.format(discardedCount)}</span> verworfen
                        </span>
                        <span>Ø {average}</span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Noch keine Matching-Läufe protokolliert.</p>
            )
          ))}
        </CardContent>
      </Card>
    </section>
  );
};

export default MatchingPage;
