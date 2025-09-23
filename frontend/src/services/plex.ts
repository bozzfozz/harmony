import api from "./api";

type PlexArtist = {
  id: string;
  name: string;
  albumCount?: number;
};

type PlexAlbum = {
  id: string;
  title: string;
  artist: string;
  year?: number;
};

type PlexTrack = {
  id: string;
  title: string;
  duration?: number;
};

type PlexStatus = {
  scanning: boolean;
  lastScan?: string;
};

const plexService = {
  getStatus: async (): Promise<PlexStatus> => {
    const { data } = await api.get("/plex/status");
    return data;
  },
  getArtists: async (): Promise<PlexArtist[]> => {
    const { data } = await api.get("/plex/artists");
    return data.artists ?? data;
  },
  getAlbums: async (artistId?: string): Promise<PlexAlbum[]> => {
    const { data } = await api.get("/plex/albums", {
      params: artistId ? { artistId } : undefined
    });
    return data.albums ?? data;
  },
  getAlbum: async (albumId: string): Promise<PlexAlbum & { tracks: PlexTrack[] }> => {
    const { data } = await api.get(`/plex/albums/${albumId}`);
    return data;
  },
  getTracks: async (albumId?: string): Promise<PlexTrack[]> => {
    const { data } = await api.get("/plex/tracks", {
      params: albumId ? { albumId } : undefined
    });
    return data.tracks ?? data;
  },
  triggerScan: async (): Promise<void> => {
    await api.post("/plex/scan");
  }
};

export type { PlexAlbum, PlexArtist, PlexStatus, PlexTrack };
export default plexService;
