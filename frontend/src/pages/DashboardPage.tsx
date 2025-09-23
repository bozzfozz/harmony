import { useEffect, useMemo, useState, type JSX } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Server, Clock } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import dashboardService, {
  DashboardOverview,
  HarmonyServiceStatus,
  JobEntry,
  defaultOverview
} from "../services/dashboard";
import type { ServiceFilters } from "../components/AppHeader";

const statusClasses: Record<HarmonyServiceStatus["status"], string> = {
  connected: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  error: "bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
  warning: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
};

const statusIcons: Record<HarmonyServiceStatus["status"], JSX.Element> = {
  connected: <CheckCircle2 className="h-4 w-4" />, 
  error: <AlertTriangle className="h-4 w-4" />, 
  warning: <AlertTriangle className="h-4 w-4" />
};

interface DashboardPageProps {
  filters: ServiceFilters;
}

const DashboardPage = ({ filters }: DashboardPageProps) => {
  const [overview, setOverview] = useState<DashboardOverview>(defaultOverview);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await dashboardService.getOverview();
        if (active) {
          setOverview(data);
        }
      } catch (err) {
        if (active) {
          console.error(err);
          setError("Dashboarddaten konnten nicht geladen werden.");
          setOverview(defaultOverview);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, []);

  const visibleServices = useMemo(() => {
    const enabledKeys = new Set(
      Object.entries(filters)
        .filter(([, value]) => value)
        .map(([key]) => key.toLowerCase())
    );

    const filterableKeys = new Set(
      Object.keys(filters).map((filterKey) => filterKey.toLowerCase())
    );

    return overview.services.filter((service) => {
      if (!enabledKeys.size) return true;
      const key = service.name.toLowerCase();

      if (filterableKeys.has(key)) {
        return enabledKeys.has(key);
      }

      return false;
    });
  }, [filters, overview.services]);

  const visibleJobs = useMemo(() => {
    const enabledKeys = new Set(
      Object.entries(filters)
        .filter(([, value]) => value)
        .map(([key]) => key.toLowerCase())
    );
    if (!enabledKeys.size) {
      return overview.jobs;
    }
    return overview.jobs.filter((job) => enabledKeys.has(job.service.toLowerCase()));
  }, [filters, overview.jobs]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Überblick über Systemzustand, verbundene Dienste und laufende Jobs deiner Harmony-Installation.
        </p>
      </header>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-center gap-3 py-4 text-sm text-destructive">
            <AlertTriangle className="h-4 w-4" />
            {error}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Übersicht</TabsTrigger>
          <TabsTrigger value="jobs">Jobs & Downloads</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          {loading ? (
            <div className="flex items-center justify-center rounded-lg border border-dashed border-border py-16 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Daten werden geladen …
            </div>
          ) : (
            <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
              <Card className="xl:col-span-1">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Server className="h-4 w-4" /> System Information
                  </CardTitle>
                  <CardDescription>
                    Kennzahlen zum Backend und angeschlossenen Komponenten.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Backend Version</span>
                    <span className="font-medium">{overview.system.backendVersion}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Database</span>
                    <Badge variant="secondary">{overview.system.databaseStatus}</Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Worker</span>
                    <Badge variant="secondary">{overview.system.workerStatus}</Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Uptime</span>
                    <span className="font-medium">{overview.system.uptime}</span>
                  </div>
                  {overview.system.hostname && (
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Host</span>
                      <span className="font-medium">{overview.system.hostname}</span>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card className="xl:col-span-2">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <CheckCircle2 className="h-4 w-4" /> Services
                  </CardTitle>
                  <CardDescription>
                    Verbindungsstatus aller integrierten Musikdienste.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {visibleServices.length ? (
                      visibleServices.map((service) => (
                        <div
                          key={service.name}
                          className="flex items-center justify-between rounded-lg border border-border/60 bg-card px-4 py-3"
                        >
                          <div>
                            <p className="font-medium leading-none">{service.name}</p>
                            {service.description && (
                              <p className="mt-1 text-xs text-muted-foreground">{service.description}</p>
                            )}
                          </div>
                          <Badge className={`flex items-center gap-1 ${statusClasses[service.status]}`}>
                            {statusIcons[service.status]}
                            <span className="capitalize">{service.status}</span>
                          </Badge>
                        </div>
                      ))
                    ) : (
                      <p className="col-span-full rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
                        Keine Dienste für die aktuelle Filterauswahl sichtbar.
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="jobs">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Clock className="h-4 w-4" /> Jobs & Downloads
              </CardTitle>
              <CardDescription>
                Letzte Aktivitäten aus Spotify, Plex, Soulseek und Beets.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Daten werden geladen …
                </div>
              ) : visibleJobs.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[160px]">Job</TableHead>
                        <TableHead>Service</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="w-[160px]">Fortschritt</TableHead>
                        <TableHead className="text-right">Zuletzt aktualisiert</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleJobs.map((job: JobEntry) => (
                        <TableRow key={job.id}>
                          <TableCell className="font-medium">{job.name}</TableCell>
                          <TableCell>{job.service}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="capitalize">
                              {job.status}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                                <div
                                  className="h-full rounded-full bg-primary transition-all"
                                  style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }}
                                />
                              </div>
                              <span className="w-10 text-xs text-muted-foreground">{Math.round(job.progress)}%</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right text-sm text-muted-foreground">{job.updatedAt}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
                  Keine aktuellen Jobs vorhanden.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default DashboardPage;
