import { useMemo } from 'react';
import { Loader2, RefreshCcw } from 'lucide-react';
import ActivityFeed from '../components/ActivityFeed';
import ServiceStatusCard from '../components/ServiceStatusCard';
import WorkerHealthCard from '../components/WorkerHealthCard';
import { useToast } from '../hooks/useToast';
import { useMutation, useQuery, useQueryClient } from '../lib/query';
import { getSystemStatus, triggerManualSync } from '../api/services/system';
import type { WorkerHealth } from '../api/types';
import { Button, Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/ui/shadcn';

const DashboardPage = () => {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ['system-status'],
    queryFn: getSystemStatus,
    refetchInterval: 20000
  });

  const syncMutation = useMutation({
    mutationFn: triggerManualSync,
    onSuccess: () => {
      toast({ title: '✅ Sync gestartet', description: 'Der manuelle Sync wurde ausgelöst.' });
      void queryClient.invalidateQueries({ queryKey: ['activity-feed'] });
      void queryClient.invalidateQueries({ queryKey: ['system-status'] });
    }
  });

  const workers = useMemo(() => Object.entries(statusQuery.data?.workers ?? {}), [statusQuery.data?.workers]);
  const hasWorkers = workers.length > 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <ServiceStatusCard connections={statusQuery.data?.connections} isLoading={statusQuery.isLoading} />
          <ActivityFeed />
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Manueller Sync</CardTitle>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Stößt eine sofortige Synchronisierung aller Dienste an.
              </p>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                Aktueller Status:{' '}
                <span className="font-medium text-slate-800 dark:text-slate-100">
                  {statusQuery.data?.status ? statusQuery.data.status : 'Unbekannt'}
                </span>
              </p>
            </CardContent>
            <CardFooter>
              <Button
                type="button"
                onClick={() => void syncMutation.mutate(undefined)}
                disabled={syncMutation.isPending}
                className="inline-flex items-center gap-2"
              >
                {syncMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    Synchronisiere…
                  </>
                ) : (
                  <>
                    <RefreshCcw className="h-4 w-4" aria-hidden /> Sync auslösen
                  </>
                )}
              </Button>
            </CardFooter>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Worker-Zustand</CardTitle>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Übersicht über die aktiven Harmony-Worker.
              </p>
            </CardHeader>
            <CardContent>
              {statusQuery.isLoading ? (
                <div className="flex items-center justify-center py-6 text-slate-500">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> Lädt Worker-Daten…
                </div>
              ) : hasWorkers ? (
                <div className="grid gap-4">
                  {workers.map(([name, meta]) => (
                    <WorkerHealthCard
                      key={name}
                      workerName={name}
                      lastSeen={(meta as WorkerHealth)?.last_seen}
                      queueSize={(meta as WorkerHealth)?.queue_size}
                      status={(meta as WorkerHealth)?.status}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Keine aktiven Worker registriert.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default DashboardPage;
