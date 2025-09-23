import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactNode } from "react";

import { SearchProvider } from "../hooks/useGlobalSearch";
import SpotifyPage from "../pages/SpotifyPage";
import type { ServiceFilters } from "../components/AppHeader";
import settingsService from "../services/settings";

jest.mock("../services/settings", () => {
  const actual = jest.requireActual("../services/settings");
  return {
    __esModule: true,
    default: {
      ...actual.default,
      getSettings: jest.fn(),
      saveSettings: jest.fn()
    },
    defaultSettings: actual.defaultSettings
  };
});

jest.mock("../services/spotify", () => {
  const actual = jest.requireActual("../services/spotify");
  return {
    __esModule: true,
    default: {
      ...actual.default,
      getStatus: jest.fn().mockResolvedValue({ connected: true, lastSync: "vor 1h" }),
      getPlaylists: jest.fn().mockResolvedValue([]),
      searchTracks: jest.fn().mockResolvedValue([])
    }
  };
});

const filters: ServiceFilters = {
  spotify: true,
  plex: true,
  soulseek: true
};

const renderWithProviders = (ui: ReactNode) =>
  render(
    <SearchProvider value={{ term: "", setTerm: () => undefined }}>
      {ui}
    </SearchProvider>
  );

describe("Service settings", () => {
  beforeEach(() => {
    (settingsService.getSettings as jest.Mock).mockResolvedValue({
      spotifyClientId: "client",
      spotifyClientSecret: "secret",
      spotifyRedirectUri: "https://example.com",
      plexBaseUrl: "https://plex.example.com",
      plexToken: "token",
      plexLibrary: "Music",
      soulseekApiUrl: "https://sls.example.com",
      soulseekApiKey: "key"
    });
    (settingsService.saveSettings as jest.Mock).mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it("switches between overview and settings tabs", async () => {
    renderWithProviders(<SpotifyPage filters={filters} />);

    await waitFor(() => expect(settingsService.getSettings).toHaveBeenCalled());

    expect(screen.getByRole("heading", { name: /spotify status/i })).toBeInTheDocument();

    const settingsTab = screen.getByRole("tab", { name: /einstellungen/i });
    await userEvent.click(settingsTab);

    expect(screen.getByRole("heading", { name: /spotify einstellungen/i })).toBeInTheDocument();
  });

  it("renders settings returned from the api", async () => {
    renderWithProviders(<SpotifyPage filters={filters} />);

    const clientIdInput = await screen.findByLabelText(/client id/i);
    expect(clientIdInput).toHaveValue("client");
    expect(screen.getByLabelText(/client secret/i)).toHaveValue("secret");
    expect(screen.getByLabelText(/redirect uri/i)).toHaveValue("https://example.com");
  });

  it("saves updated settings", async () => {
    renderWithProviders(<SpotifyPage filters={filters} />);

    const clientIdInput = await screen.findByLabelText(/client id/i);
    await userEvent.clear(clientIdInput);
    await userEvent.type(clientIdInput, "new-client");

    await userEvent.click(screen.getByRole("button", { name: /einstellungen speichern/i }));

    await waitFor(() => {
      expect(settingsService.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({ spotifyClientId: "new-client" })
      );
    });
  });

  it("shows an error when saving fails", async () => {
    (settingsService.saveSettings as jest.Mock).mockRejectedValueOnce(new Error("fail"));
    renderWithProviders(<SpotifyPage filters={filters} />);

    const button = await screen.findByRole("button", { name: /einstellungen speichern/i });
    await userEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText(/fehler beim speichern der einstellungen/i)).toBeInTheDocument();
    });
  });
});
