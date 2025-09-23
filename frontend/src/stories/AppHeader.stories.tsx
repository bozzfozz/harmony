import type { Meta, StoryObj } from "@storybook/react";
import { useEffect, useState } from "react";

import AppHeader, { ServiceFilters } from "../components/AppHeader";

const meta: Meta<typeof AppHeader> = {
  title: "Components/AppHeader",
  component: AppHeader,
  parameters: {
    layout: "fullscreen"
  },
  args: {
    loading: false,
    searchTerm: "",
    filters: {
      spotify: true,
      plex: true,
      soulseek: true
    } satisfies ServiceFilters,
    isDarkMode: false,
    hasNewFeatures: false
  }
};

export default meta;

type Story = StoryObj<typeof AppHeader>;

const StoryWrapper = (props: Story["args"]) => {
  const [filters, setFilters] = useState<ServiceFilters>(
    props?.filters ?? { spotify: true, plex: true, soulseek: true }
  );
  const [searchTerm, setSearchTerm] = useState(props?.searchTerm ?? "");

  useEffect(() => {
    if (props?.isDarkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }

    return () => {
      document.documentElement.classList.remove("dark");
    };
  }, [props?.isDarkMode]);

  return (
    <div className="min-h-screen bg-background p-6">
      <AppHeader
        loading={props?.loading ?? false}
        onRefresh={() => console.log("refresh")}
        searchTerm={searchTerm}
        onSearchChange={setSearchTerm}
        filters={filters}
        onFilterChange={setFilters}
        isDarkMode={props?.isDarkMode ?? false}
        onThemeToggle={() => console.log("theme toggle")}
        onGoHome={() => console.log("go home")}
        onToggleSidebar={() => console.log("toggle sidebar")}
        onShowWhatsNew={props?.onShowWhatsNew}
        onShowNotifications={() => console.log("notifications")}
        hasNewFeatures={props?.hasNewFeatures}
      />
    </div>
  );
};

export const Default: Story = {
  render: (args) => <StoryWrapper {...args} />
};

export const SpotifyFilterActive: Story = {
  render: (args) => (
    <StoryWrapper
      {...args}
      filters={{ spotify: true, plex: false, soulseek: false }}
    />
  )
};

export const Loading: Story = {
  render: (args) => <StoryWrapper {...args} loading />
};

export const DarkMode: Story = {
  render: (args) => <StoryWrapper {...args} isDarkMode />
};

export const WhatsNew: Story = {
  render: (args) => (
    <StoryWrapper
      {...args}
      hasNewFeatures
      onShowWhatsNew={() => console.log("show what's new")}
    />
  )
};
