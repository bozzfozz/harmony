import api from "./api";

type SoulseekDownload = {
  id: string;
  filename: string;
  progress: number;
  status: "queued" | "downloading" | "completed" | "failed" | "cancelled";
  updatedAt?: string;
};

type SoulseekSearchResult = {
  id: string;
  filename: string;
  size: number;
  user: string;
};

const soulseekService = {
  getStatus: async () => {
    const { data } = await api.get("/soulseek/status");
    return data;
  },
  search: async (query: string): Promise<SoulseekSearchResult[]> => {
    if (!query) return [];
    const { data } = await api.post("/soulseek/search", { query });
    const results = Array.isArray(data?.results) ? data.results : [];
    return results.map((item: any, index: number) => ({
      id: String(item.id ?? item.transferId ?? index),
      filename: String(item.filename ?? item.name ?? ""),
      size: Number(item.size ?? item.filesize ?? 0),
      user: String(item.user ?? item.username ?? "")
    }));
  },
  getDownloads: async (): Promise<SoulseekDownload[]> => {
    const { data } = await api.get("/soulseek/downloads");
    const downloads = Array.isArray(data?.downloads) ? data.downloads : [];
    return downloads.map((download: any) => ({
      id: String(download.id ?? download.download_id ?? ""),
      filename: String(download.filename ?? download.name ?? ""),
      progress: Number(download.progress ?? 0),
      status: (download.state as SoulseekDownload["status"]) ?? "queued",
      updatedAt: download.updated_at ?? download.updatedAt ?? undefined
    }));
  },
  cancelDownload: async (downloadId: string) => {
    await api.delete(`/soulseek/download/${downloadId}`);
  }
};

export type { SoulseekDownload, SoulseekSearchResult };
export default soulseekService;
