import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

export interface ServiceStatusCardProps {
  connections?: Record<string, string>;
  isLoading?: boolean;
}

const SERVICE_LABELS: Record<string, string> = {
  spotify: 'Spotify',
  plex: 'Plex',
  soulseek: 'Soulseek'
};

const statusMeta = (status?: string) => {
  const normalized = status?.toLowerCase();
  if (normalized === 'ok' || normalized === 'connected') {
    return { badge: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300', label: 'Verbunden', icon: '✅' };
  }
  if (normalized === 'fail' || normalized === 'error') {
    return { badge: 'bg-rose-500/15 text-rose-700 dark:text-rose-300', label: 'Fehlgeschlagen', icon: '❌' };
  }
  if (normalized === 'blocked') {
    return { badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300', label: 'Blockiert', icon: '⚠️' };
  }
  return { badge: 'bg-slate-200/60 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300', label: 'Unbekannt', icon: '❔' };
};

const formatLabel = (key: string) => SERVICE_LABELS[key] ?? key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());

const ServiceStatusCard = ({ connections, isLoading = false }: ServiceStatusCardProps) => {
  const entries = connections ? Object.entries(connections) : [];
  const knownEntries = Object.keys(SERVICE_LABELS)
    .filter((key) => entries.some(([candidate]) => candidate === key))
    .map((key) => [key, connections?.[key]] as const);
  const additionalEntries = entries.filter(([key]) => !(key in SERVICE_LABELS));
  const allEntries = [...knownEntries, ...additionalEntries];

  return (
    <Card data-testid="service-status-card">
      <CardHeader className="space-y-1">
        <CardTitle className="text-lg font-semibold">Service-Verbindungen</CardTitle>
        <p className="text-sm text-slate-500 dark:text-slate-400">Status der hinterlegten Zugangsdaten.</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-sm text-slate-500">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Lädt…
          </div>
        ) : allEntries.length > 0 ? (
          allEntries.map(([key, status]) => {
            const meta = statusMeta(status);
            return (
              <div key={key} className="flex items-center justify-between rounded-lg border border-slate-200/70 px-3 py-2 dark:border-slate-800/70">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{formatLabel(key)}</span>
                <span
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${meta.badge}`}
                  aria-label={meta.label}
                >
                  <span aria-hidden>{meta.icon}</span>
                  {meta.label}
                </span>
              </div>
            );
          })
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">Keine Verbindungsinformationen verfügbar.</p>
        )}
      </CardContent>
    </Card>
  );
};

export default ServiceStatusCard;
