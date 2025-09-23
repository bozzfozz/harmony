import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Server } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import dashboardService, {
  type DashboardOverview,
  type HarmonyServiceStatus,
  type JobEntry
} from "../services/dashboard";
import type { ServiceFilters } from "../components/AppHeader";

const statusClasses: Record<HarmonyServiceStatus["status"], string> = {
  connected: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  disconnected: "bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
  unknown: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
};

const statusIcons: Record<HarmonyServiceStatus["status"], JSX.Element> = {
  connected: <CheckCircle2 className="h-4 w-4" />,
  disconnected: <AlertTriangle className="h-4 w-4" />,
  unknown: <AlertTriangle className="h-4 w-4" />
};

interface DashboardPageProps {
  filters: ServiceFilters;
}

const DashboardPage = ({ filters }: DashboardPageProps) => {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
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
        console.error(err);
        if (active) {
          setError("Dashboarddaten konnten nicht geladen werden.");
          setOverview(null);
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
    if (!overview) return [];
    const enabled = Object.entries(filters)
      .filter(([, value]) => value)
      .map(([key]) => key.toLowerCase());
    if (!enabled.length) {
      return overview.services;
    }
    return overview.services.filter((service) => enabled.includes(service.name.toLowerCase()));
  }, [filters, overview]);

  const visibleJobs = useMemo(() => {
    if (!overview) return [];
    const enabled = Object.entries(filters)
      .filter(([, value]) => value)
      .map(([key]) => key.toLowerCase());
    if (!enabled.length) {
      return overview.jobs;
    }
    return overview.jobs.filter((job) => enabled.includes(job.service.toLowerCase()));
  }, [filters, overview]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Überblick über Systemzustand, verbundene Dienste und laufende Soulseek-Downloads deiner Harmony-Installation.
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
          <TabsTrigger value="jobs">Downloads</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          {loading ? (
            <div className="flex items-center justify-center rounded-lg border border-dashed border-border py-16 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Daten werden geladen …
            </div>
          ) : overview ? (
            <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
              <Card className="xl:col-span-1">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Server className="h-4 w-4" /> System Information
                  </CardTitle>
                  <CardDescription>Statusinformationen des Harmony Backends.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Backend Version</span>
                    <span className="font-medium">{overview.system.backendVersion}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Status</span>
                    <Badge variant="secondary">{overview.system.status}</Badge>
                  </div>
                </CardContent>
              </Card>

              <Card className="xl:col-span-2">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <CheckCircle2 className="h-4 w-4" /> Services
                  </CardTitle>
                  <CardDescription>Verbindungsstatus aller integrierten Musikdienste.</CardDescription>
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
                            {service.meta?.detail ? (
                              <p className="mt-1 text-xs text-muted-foreground">
                                {String(service.meta.detail)}
                              </p>
                            ) : null}
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
          ) : (
            <div className="rounded-lg border border-dashed border-border py-16 text-center text-sm text-muted-foreground">
              Keine Daten verfügbar.
            </div>
          )}
        </TabsContent>

        <TabsContent value="jobs">
          {loading ? (
            <div className="flex items-center justify-center rounded-lg border border-dashed border-border py-16 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Daten werden geladen …
            </div>
          ) : visibleJobs.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Download</TableHead>
                  <TableHead>Service</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Fortschritt</TableHead>
                  <TableHead>Aktualisiert</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleJobs.map((job: JobEntry) => (
                  <TableRow key={job.id}>
                    <TableCell className="max-w-[16rem] truncate" title={job.name}>
                      {job.name}
                    </TableCell>
                    <TableCell>{job.service}</TableCell>
                    <TableCell>{job.status}</TableCell>
                    <TableCell>{Math.round(job.progress)}%</TableCell>
                    <TableCell>{new Date(job.updatedAt).toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="rounded-lg border border-dashed border-border py-16 text-center text-sm text-muted-foreground">
              Keine aktiven Downloads vorhanden.
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default DashboardPage;
