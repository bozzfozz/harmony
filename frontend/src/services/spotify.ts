import api from "./api";

type SpotifyTrack = {
  id: string;
  name: string;
  album: string;
  artist: string;
  durationMs: number;
};

type SpotifyPlaylist = {
  id: string;
  name: string;
  description?: string;
  trackCount: number;
  updatedAt?: string;
};

type SpotifyStatus = {
  connected: boolean;
  lastSync?: string;
};

const mapTrack = (item: Record<string, any>): SpotifyTrack => ({
  id: String(item.id ?? item.uri ?? ""),
  name: String(item.name ?? "Unbekannter Titel"),
  album: String(item.album?.name ?? ""),
  artist: Array.isArray(item.artists)
    ? item.artists.map((artist: any) => artist.name).filter(Boolean).join(", ")
    : String(item.artist ?? item.artists ?? ""),
  durationMs: Number(item.duration_ms ?? item.durationMs ?? 0)
});

const spotifyService = {
  getStatus: async (): Promise<SpotifyStatus> => {
    const { data } = await api.get("/spotify/status");
    return {
      connected: data?.status === "connected",
      lastSync: data?.last_scan ?? data?.lastScan ?? undefined
    };
  },
  searchTracks: async (query: string): Promise<SpotifyTrack[]> => {
    if (!query) return [];
    const { data } = await api.get("/spotify/search/tracks", { params: { query } });
    const items = Array.isArray(data?.items)
      ? data.items
      : Array.isArray(data?.tracks?.items)
        ? data.tracks.items
        : [];
    return items.map(mapTrack);
  },
  searchArtists: async (query: string) => {
    if (!query) return [];
    const { data } = await api.get("/spotify/search/artists", { params: { query } });
    return Array.isArray(data?.items) ? data.items : [];
  },
  searchAlbums: async (query: string) => {
    if (!query) return [];
    const { data } = await api.get("/spotify/search/albums", { params: { query } });
    return Array.isArray(data?.items) ? data.items : [];
  },
  getPlaylists: async (): Promise<SpotifyPlaylist[]> => {
    const { data } = await api.get("/spotify/playlists");
    const playlists = Array.isArray(data?.playlists) ? data.playlists : [];
    return playlists.map((playlist: any) => ({
      id: String(playlist.id ?? playlist.uri ?? ""),
      name: String(playlist.name ?? "Unbenannte Playlist"),
      description: playlist.description ?? undefined,
      trackCount: Number(playlist.track_count ?? playlist.tracks ?? 0),
      updatedAt: playlist.updated_at ?? playlist.updatedAt ?? undefined
    }));
  }
};

export type { SpotifyPlaylist, SpotifyStatus, SpotifyTrack };
export default spotifyService;
