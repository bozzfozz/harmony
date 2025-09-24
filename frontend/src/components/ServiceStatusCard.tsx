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

const formatStatus = (status?: string) => {
  if (status === 'ok') {
    return { icon: '✅', label: 'Verbunden' };
  }
  if (status === 'fail') {
    return { icon: '❌', label: 'Fehlgeschlagen' };
  }
  return { icon: '❔', label: 'Unbekannt' };
};

const ServiceStatusCard = ({ connections, isLoading = false }: ServiceStatusCardProps) => {
  return (
    <Card data-testid="service-status-card">
      <CardHeader>
        <CardTitle>Service-Verbindungen</CardTitle>
        <p className="text-sm text-muted-foreground">
          Übersicht über die zuletzt gespeicherten Zugangsdaten.
        </p>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {Object.entries(SERVICE_LABELS).map(([key, label]) => {
          const statusMeta = formatStatus(connections?.[key]);
          return (
            <div key={key} className="flex items-center justify-between">
              <span>{label}</span>
              <span aria-label={statusMeta.label} className="flex items-center gap-2 font-medium">
                <span aria-hidden>{statusMeta.icon}</span>
                {isLoading ? 'Prüfe…' : statusMeta.label}
              </span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
};

export default ServiceStatusCard;
