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
};

type SpotifyPlaylistWithTracks = SpotifyPlaylist & {
  tracks: SpotifyTrack[];
};

type SpotifyStatus = {
  connected: boolean;
  lastSync?: string;
};

const spotifyService = {
  getStatus: async (): Promise<SpotifyStatus> => {
    const { data } = await api.get("/spotify/status");
    return data;
  },
  searchTracks: async (query: string): Promise<SpotifyTrack[]> => {
    if (!query) return [];
    const { data } = await api.get("/spotify/search", {
      params: { query }
    });
    return data.tracks ?? data;
  },
  searchArtists: async (query: string) => {
    if (!query) return [];
    const { data } = await api.get("/spotify/search/artists", {
      params: { query }
    });
    return data.artists ?? data;
  },
  searchAlbums: async (query: string) => {
    if (!query) return [];
    const { data } = await api.get("/spotify/search/albums", {
      params: { query }
    });
    return data.albums ?? data;
  },
  getPlaylists: async (): Promise<SpotifyPlaylist[]> => {
    const { data } = await api.get("/spotify/playlists");
    return data.playlists ?? data;
  },
  getPlaylist: async (playlistId: string): Promise<SpotifyPlaylistWithTracks> => {
    const { data } = await api.get(`/spotify/playlists/${playlistId}`);
    return data;
  },
  getTrack: async (trackId: string): Promise<SpotifyTrack> => {
    const { data } = await api.get(`/spotify/tracks/${trackId}`);
    return data;
  }
};

export type { SpotifyPlaylist, SpotifyPlaylistWithTracks, SpotifyStatus, SpotifyTrack };
export default spotifyService;
