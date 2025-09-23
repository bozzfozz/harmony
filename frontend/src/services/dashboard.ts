import api from "./api";

export type SystemInformation = {
  backendVersion: string;
  status: string;
};

export type HarmonyServiceStatus = {
  name: string;
  status: "connected" | "disconnected" | "unknown";
  meta?: Record<string, unknown>;
};

export type JobEntry = {
  id: string;
  name: string;
  service: string;
  status: string;
  progress: number;
  updatedAt: string;
};

type DashboardOverview = {
  system: SystemInformation;
  services: HarmonyServiceStatus[];
  jobs: JobEntry[];
};

const mapStatus = (name: string, statusValue: any): HarmonyServiceStatus => {
  const status = typeof statusValue?.status === "string" ? statusValue.status : undefined;
  return {
    name,
    status:
      status === "connected" || status === "disconnected"
        ? status
        : status === "error"
          ? "disconnected"
          : "unknown",
    meta: statusValue ?? undefined
  };
};

const mapDownloadsToJobs = (downloads: any[]): JobEntry[] =>
  downloads.map((download) => ({
    id: String(download.id ?? download.download_id ?? ""),
    name: String(download.filename ?? download.name ?? "Download"),
    service: "Soulseek",
    status: String(download.state ?? "unknown"),
    progress: Number(download.progress ?? 0),
    updatedAt: String(download.updated_at ?? download.updatedAt ?? new Date().toISOString())
  }));

const dashboardService = {
  getOverview: async (): Promise<DashboardOverview> => {
    const [systemRes, spotifyRes, plexRes, soulseekRes, downloadsRes] = await Promise.allSettled([
      api.get("/"),
      api.get("/spotify/status"),
      api.get("/plex/status"),
      api.get("/soulseek/status"),
      api.get("/soulseek/downloads")
    ]);

    const system: SystemInformation = {
      backendVersion:
        systemRes.status === "fulfilled" ? systemRes.value.data?.version ?? "unknown" : "unknown",
      status: systemRes.status === "fulfilled" ? systemRes.value.data?.status ?? "unknown" : "unknown"
    };

    const services: HarmonyServiceStatus[] = [
      mapStatus("Spotify", spotifyRes.status === "fulfilled" ? spotifyRes.value.data : null),
      mapStatus("Plex", plexRes.status === "fulfilled" ? plexRes.value.data : null),
      mapStatus("Soulseek", soulseekRes.status === "fulfilled" ? soulseekRes.value.data : null)
    ];

    const downloads =
      downloadsRes.status === "fulfilled"
        ? Array.isArray(downloadsRes.value.data?.downloads)
          ? downloadsRes.value.data.downloads
          : []
        : [];

    const jobs = mapDownloadsToJobs(downloads);

    return {
      system,
      services,
      jobs
    };
  }
};

export type { DashboardOverview };
export { mapDownloadsToJobs };
export default dashboardService;
