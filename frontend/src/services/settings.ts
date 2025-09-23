import api from "./api";

type SettingsPayload = {
  spotifyClientId: string;
  spotifyClientSecret: string;
  spotifyRedirectUri: string;
  plexBaseUrl: string;
  plexToken: string;
  plexLibrary: string;
  soulseekApiUrl: string;
  soulseekApiKey: string;
};

type RawSettingsResponse = {
  settings?: Record<string, string | null>;
  updated_at?: string;
};

const defaultSettings: SettingsPayload = {
  spotifyClientId: "",
  spotifyClientSecret: "",
  spotifyRedirectUri: "",
  plexBaseUrl: "",
  plexToken: "",
  plexLibrary: "",
  soulseekApiUrl: "",
  soulseekApiKey: ""
};

const keyMap: Record<keyof SettingsPayload, string> = {
  spotifyClientId: "SPOTIFY_CLIENT_ID",
  spotifyClientSecret: "SPOTIFY_CLIENT_SECRET",
  spotifyRedirectUri: "SPOTIFY_REDIRECT_URI",
  plexBaseUrl: "PLEX_BASE_URL",
  plexToken: "PLEX_TOKEN",
  plexLibrary: "PLEX_LIBRARY",
  soulseekApiUrl: "SLSKD_URL",
  soulseekApiKey: "SLSKD_API_KEY"
};

const mapResponseToSettings = (data: RawSettingsResponse | undefined): SettingsPayload => {
  const entries = data?.settings ?? {};
  return {
    spotifyClientId: (entries[keyMap.spotifyClientId] ?? "") as string,
    spotifyClientSecret: (entries[keyMap.spotifyClientSecret] ?? "") as string,
    spotifyRedirectUri: (entries[keyMap.spotifyRedirectUri] ?? "") as string,
    plexBaseUrl: (entries[keyMap.plexBaseUrl] ?? "") as string,
    plexToken: (entries[keyMap.plexToken] ?? "") as string,
    plexLibrary: (entries[keyMap.plexLibrary] ?? "") as string,
    soulseekApiUrl: (entries[keyMap.soulseekApiUrl] ?? "") as string,
    soulseekApiKey: (entries[keyMap.soulseekApiKey] ?? "") as string
  };
};

const settingsService = {
  getSettings: async (): Promise<SettingsPayload> => {
    const { data } = await api.get<RawSettingsResponse>("/settings");
    return mapResponseToSettings(data);
  },
  saveSettings: async (payload: SettingsPayload): Promise<void> => {
    const entries = Object.entries(payload) as [keyof SettingsPayload, string][];
    for (const [key, value] of entries) {
      const apiKey = keyMap[key];
      await api.post("/settings", { key: apiKey, value });
    }
  }
};

export type { SettingsPayload };
export { defaultSettings };
export default settingsService;
