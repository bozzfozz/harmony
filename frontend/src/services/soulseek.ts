import api from "./api";

type SoulseekDownload = {
  id: string;
  filename: string;
  progress: number;
  status: "queued" | "downloading" | "completed" | "failed" | "cancelled";
  speed?: number;
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
    const { data } = await api.get("/soulseek/search", {
      params: { query }
    });
    return data.results ?? data;
  },
  getDownloads: async (): Promise<SoulseekDownload[]> => {
    const { data } = await api.get("/soulseek/downloads");
    return data.downloads ?? data;
  },
  cancelDownload: async (downloadId: string) => {
    await api.delete(`/soulseek/downloads/${downloadId}`);
  }
};

export type { SoulseekDownload, SoulseekSearchResult };
export default soulseekService;
