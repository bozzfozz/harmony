import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";

import AppHeader, { ServiceFilters } from "../components/AppHeader";

const renderHeader = (props?: Partial<ComponentProps<typeof AppHeader>>) => {
  const defaultFilters: ServiceFilters = { spotify: true, plex: true, soulseek: true };
  const onRefresh = jest.fn();
  const onSearchChange = jest.fn();
  const onFilterChange = jest.fn();
  const onThemeToggle = jest.fn();
  const onGoHome = jest.fn();
  const onToggleSidebar = jest.fn();
  const onShowNotifications = jest.fn();

  render(
    <AppHeader
      loading={false}
      onRefresh={onRefresh}
      searchTerm=""
      onSearchChange={onSearchChange}
      filters={defaultFilters}
      onFilterChange={onFilterChange}
      isDarkMode={false}
      onThemeToggle={onThemeToggle}
      onGoHome={onGoHome}
      onToggleSidebar={onToggleSidebar}
      onShowNotifications={onShowNotifications}
      {...props}
    />
  );

  return {
    onRefresh,
    onSearchChange,
    onFilterChange,
    onThemeToggle,
    onGoHome,
    onToggleSidebar,
    onShowNotifications
  };
};

describe("AppHeader", () => {
  it("renders the Harmony logo", () => {
    renderHeader();

    expect(screen.getByLabelText(/harmony logo/i)).toBeInTheDocument();
    expect(screen.getByText(/harmony/i)).toBeInTheDocument();
  });

  it("debounces search input before triggering callback", async () => {
    jest.useFakeTimers();
    const { onSearchChange } = renderHeader();
    const input = screen.getByRole("textbox", {
      name: /search tracks, artists and albums/i
    });

    await userEvent.type(input, "Lo-fi beats");

    expect(onSearchChange).not.toHaveBeenCalled();

    await act(async () => {
      jest.advanceTimersByTime(350);
    });

    expect(onSearchChange).toHaveBeenCalledTimes(1);
    expect(onSearchChange).toHaveBeenCalledWith("Lo-fi beats");

    jest.useRealTimers();
  });

  it("toggles filters when clicking on filter buttons", async () => {
    const { onFilterChange } = renderHeader();

    const spotifyButton = screen.getByRole("button", { name: "Spotify" });
    await userEvent.click(spotifyButton);

    expect(onFilterChange).toHaveBeenCalledWith({
      spotify: false,
      plex: true,
      soulseek: true
    });
  });

  it("invokes refresh callback", async () => {
    const { onRefresh } = renderHeader();

    const refreshButton = screen.getByRole("button", { name: /refresh data/i });
    await userEvent.click(refreshButton);

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("invokes theme toggle callback", async () => {
    const { onThemeToggle } = renderHeader();

    const themeButton = screen.getByRole("button", { name: /switch to dark mode/i });
    await userEvent.click(themeButton);

    expect(onThemeToggle).toHaveBeenCalledTimes(1);
  });

  it("opens notifications", async () => {
    const { onShowNotifications } = renderHeader();

    const notificationsButton = screen.getByRole("button", { name: /benachrichtigungen anzeigen/i });
    await userEvent.click(notificationsButton);

    expect(onShowNotifications).toHaveBeenCalledTimes(1);
  });
});
