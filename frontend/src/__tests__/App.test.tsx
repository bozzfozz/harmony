import { render, screen, waitFor } from "@testing-library/react";
import App from "../App";
import spotifyService from "../services/spotify";
import plexService from "../services/plex";
import soulseekService from "../services/soulseek";
import dashboardService from "../services/dashboard";
import settingsService from "../services/settings";

jest.mock("../services/spotify", () => {
  const actual = jest.requireActual("../services/spotify");
  return {
    __esModule: true,
    ...actual,
    default: {
      ...actual.default,
      getStatus: jest.fn().mockResolvedValue({ connected: true, lastSync: "vor 1h" }),
      searchTracks: jest.fn().mockResolvedValue([]),
      getPlaylists: jest.fn().mockResolvedValue([])
    }
  };
});

jest.mock("../services/plex", () => {
  const actual = jest.requireActual("../services/plex");
  return {
    __esModule: true,
    ...actual,
    default: {
      ...actual.default,
      getStatus: jest.fn().mockResolvedValue({ status: "connected", sessions: [], library: {} }),
      getSections: jest.fn().mockResolvedValue([]),
      getSessions: jest.fn().mockResolvedValue([]),
      getSectionItems: jest.fn().mockResolvedValue([])
    }
  };
});

jest.mock("../services/soulseek", () => {
  const actual = jest.requireActual("../services/soulseek");
  return {
    __esModule: true,
    ...actual,
    default: {
      ...actual.default,
      getDownloads: jest.fn().mockResolvedValue([]),
      search: jest.fn().mockResolvedValue([]),
      cancelDownload: jest.fn().mockResolvedValue(undefined)
    }
  };
});

jest.mock("../services/dashboard", () => {
  return {
    __esModule: true,
    default: {
      getOverview: jest.fn().mockResolvedValue({
        system: {
          backendVersion: "1.0.0",
          status: "ok"
        },
        services: [],
        jobs: []
      })
    }
  };
});

jest.mock("../services/settings", () => {
  const actual = jest.requireActual("../services/settings");
  return {
    __esModule: true,
    default: {
      ...actual.default,
      getSettings: jest.fn().mockResolvedValue(actual.defaultSettings),
      saveSettings: jest.fn().mockResolvedValue(undefined)
    },
    defaultSettings: actual.defaultSettings
  };
});

describe("App", () => {
  beforeEach(() => {
    window.matchMedia = window.matchMedia ||
      (() => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
  });

  it("renders the navbar and triggers service calls on load", async () => {
    window.history.pushState({}, "", "/dashboard");

    render(<App />);

    expect(await screen.findByText(/harmony/i)).toBeInTheDocument();

    await waitFor(() => {
      expect((spotifyService.getStatus as jest.Mock)).toHaveBeenCalled();
      expect((plexService.getStatus as jest.Mock)).toHaveBeenCalled();
      expect((dashboardService.getOverview as jest.Mock)).toHaveBeenCalled();
      expect((settingsService.getSettings as jest.Mock)).toHaveBeenCalled();
    });
  });
});
