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

const mapResponseToSettings = (
  data: Partial<SettingsPayload> & Record<string, unknown>
): SettingsPayload => ({
  spotifyClientId:
    (data.spotifyClientId as string | undefined) ??
    (data.SPOTIFY_CLIENT_ID as string | undefined) ??
    defaultSettings.spotifyClientId,
  spotifyClientSecret:
    (data.spotifyClientSecret as string | undefined) ??
    (data.SPOTIFY_CLIENT_SECRET as string | undefined) ??
    defaultSettings.spotifyClientSecret,
  spotifyRedirectUri:
    (data.spotifyRedirectUri as string | undefined) ??
    (data.SPOTIFY_REDIRECT_URI as string | undefined) ??
    defaultSettings.spotifyRedirectUri,
  plexBaseUrl:
    (data.plexBaseUrl as string | undefined) ??
    (data.PLEX_BASE_URL as string | undefined) ??
    defaultSettings.plexBaseUrl,
  plexToken:
    (data.plexToken as string | undefined) ??
    (data.PLEX_TOKEN as string | undefined) ??
    defaultSettings.plexToken,
  plexLibrary:
    (data.plexLibrary as string | undefined) ??
    (data.PLEX_LIBRARY as string | undefined) ??
    defaultSettings.plexLibrary,
  soulseekApiUrl:
    (data.soulseekApiUrl as string | undefined) ??
    (data.SLSKD_URL as string | undefined) ??
    defaultSettings.soulseekApiUrl,
  soulseekApiKey:
    (data.soulseekApiKey as string | undefined) ??
    (data.SLSKD_API_KEY as string | undefined) ??
    defaultSettings.soulseekApiKey
});

const toRequestBody = (payload: SettingsPayload) => ({
  ...payload,
  SPOTIFY_CLIENT_ID: payload.spotifyClientId,
  SPOTIFY_CLIENT_SECRET: payload.spotifyClientSecret,
  SPOTIFY_REDIRECT_URI: payload.spotifyRedirectUri,
  PLEX_BASE_URL: payload.plexBaseUrl,
  PLEX_TOKEN: payload.plexToken,
  PLEX_LIBRARY: payload.plexLibrary,
  SLSKD_URL: payload.soulseekApiUrl,
  SLSKD_API_KEY: payload.soulseekApiKey
});

const settingsService = {
  getSettings: async (): Promise<SettingsPayload> => {
    const { data } = await api.get("/settings");
    return mapResponseToSettings(data ?? {});
  },
  saveSettings: async (payload: SettingsPayload) => {
    const body = toRequestBody({ ...defaultSettings, ...payload });
    const { data } = await api.post("/settings", body);
    return data;
  }
};

export type { SettingsPayload };
export { defaultSettings };
export default settingsService;
