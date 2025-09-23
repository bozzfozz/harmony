import api from "./api";

type MatchingSummary = {
  matched: number;
  missing: number;
  lastRun?: string;
};

const matchingService = {
  matchSpotifyToPlex: async (): Promise<MatchingSummary> => {
    const { data } = await api.post("/matching/spotify-to-plex");
    return data;
  },
  matchSpotifyToSoulseek: async (): Promise<MatchingSummary> => {
    const { data } = await api.post("/matching/spotify-to-soulseek");
    return data;
  }
};

export type { MatchingSummary };
export default matchingService;
