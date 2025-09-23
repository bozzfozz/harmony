import api from "./api";

type SystemInformation = {
  backendVersion: string;
  databaseStatus: string;
  workerStatus: string;
  uptime: string;
  hostname?: string;
};

type HarmonyServiceStatus = {
  name: string;
  status: "connected" | "error" | "warning";
  lastUpdated?: string;
  description?: string;
};

type JobEntry = {
  id: string;
  name: string;
  service: string;
  status: "running" | "queued" | "completed" | "failed";
  progress: number;
  updatedAt: string;
};

type DashboardOverview = {
  system: SystemInformation;
  services: HarmonyServiceStatus[];
  jobs: JobEntry[];
};

const defaultOverview: DashboardOverview = {
  system: {
    backendVersion: "unknown",
    databaseStatus: "unknown",
    workerStatus: "unknown",
    uptime: "–"
  },
  services: [],
  jobs: []
};

const dashboardService = {
  getOverview: async (): Promise<DashboardOverview> => {
    const { data } = await api.get("/dashboard");
    const system = {
      ...defaultOverview.system,
      ...(data?.system ?? {})
    } as SystemInformation;
    const services = Array.isArray(data?.services)
      ? (data.services as HarmonyServiceStatus[])
      : defaultOverview.services;
    const jobs = Array.isArray(data?.jobs)
      ? (data.jobs as JobEntry[])
      : defaultOverview.jobs;

    return {
      system,
      services,
      jobs
    };
  }
};

export type { DashboardOverview, HarmonyServiceStatus, JobEntry, SystemInformation };
export { defaultOverview };
export default dashboardService;
