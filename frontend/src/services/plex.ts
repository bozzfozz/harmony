import api from "./api";

type PlexStatus = {
  status: "connected" | "disconnected";
  sessions?: any;
  library?: any;
};

type PlexLibrarySection = {
  id: string;
  title: string;
  type?: string;
};

type PlexSession = {
  id: string;
  title: string;
  user?: string;
  state?: string;
};

type PlexLibraryItem = {
  id: string;
  title: string;
  parent?: string;
  type?: string;
  year?: number;
};

const plexService = {
  getStatus: async (): Promise<PlexStatus> => {
    const { data } = await api.get("/plex/status");
    return {
      status: (data?.status as PlexStatus["status"]) ?? "disconnected",
      sessions: data?.sessions,
      library: data?.library
    };
  },
  getSections: async (): Promise<PlexLibrarySection[]> => {
    const { data } = await api.get("/plex/library/sections");
    const container = data?.MediaContainer;
    const sections = Array.isArray(container?.Directory) ? container.Directory : [];
    return sections.map((section: any) => ({
      id: String(section.key ?? section.uuid ?? ""),
      title: String(section.title ?? "Unbenannte Sektion"),
      type: section.type ?? undefined
    }));
  },
  getSessions: async (): Promise<PlexSession[]> => {
    const { data } = await api.get("/plex/status/sessions");
    const sessions = Array.isArray(data?.MediaContainer?.Metadata)
      ? data.MediaContainer.Metadata
      : Array.isArray(data) ? data : [];
    return sessions.map((session: any, index: number) => ({
      id: String(session.sessionKey ?? session.id ?? index),
      title: String(session.title ?? session.grandparentTitle ?? session.parentTitle ?? "Unbekannt"),
      user: session.user?.title ?? session.User?.title ?? session.username ?? undefined,
      state: session.viewOffset ? "playing" : session.state ?? undefined
    }));
  },
  getSectionItems: async (sectionId: string): Promise<PlexLibraryItem[]> => {
    const { data } = await api.get(`/plex/library/sections/${sectionId}/all`);
    const container = data?.MediaContainer;
    const items = Array.isArray(container?.Metadata) ? container.Metadata : [];
    return items.map((item: any, index: number) => ({
      id: String(item.ratingKey ?? item.key ?? index),
      title: String(item.title ?? "Unbenannter Eintrag"),
      parent: item.parentTitle ?? item.grandparentTitle ?? undefined,
      type: item.type ?? undefined,
      year: typeof item.year === "number" ? item.year : undefined
    }));
  }
};

export type { PlexLibraryItem, PlexLibrarySection, PlexSession, PlexStatus };
export default plexService;
