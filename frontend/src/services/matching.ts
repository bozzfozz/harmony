import api from "./api";

type MatchingResponse = {
  bestMatch: Record<string, unknown> | null;
  confidence: number;
};

const matchingService = {
  matchSpotifyToPlex: async (payload: Record<string, unknown>): Promise<MatchingResponse> => {
    const { data } = await api.post("/matching/spotify-to-plex", payload);
    return {
      bestMatch: data?.best_match ?? data?.bestMatch ?? null,
      confidence: Number(data?.confidence ?? 0)
    };
  },
  matchSpotifyToSoulseek: async (payload: Record<string, unknown>): Promise<MatchingResponse> => {
    const { data } = await api.post("/matching/spotify-to-soulseek", payload);
    return {
      bestMatch: data?.best_match ?? data?.bestMatch ?? null,
      confidence: Number(data?.confidence ?? 0)
    };
  }
};

export type { MatchingResponse };
export default matchingService;
