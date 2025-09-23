import { NavLink } from "react-router-dom";
import { LayoutDashboard, Music, Radio, Share2, Shuffle, Settings, Disc } from "lucide-react";
import { cn } from "../lib/utils";

const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/spotify", label: "Spotify", icon: Music },
  { to: "/plex", label: "Plex", icon: Share2 },
  { to: "/soulseek", label: "Soulseek", icon: Radio },
  { to: "/beets", label: "Beets", icon: Disc },
  { to: "/matching", label: "Matching", icon: Shuffle },
  { to: "/settings", label: "Settings", icon: Settings }
];

interface SidebarProps {
  onNavigate?: () => void;
}

const Sidebar = ({ onNavigate }: SidebarProps) => {
  return (
    <nav className="flex h-full flex-col gap-1 bg-sidebar/50 p-4 text-sidebar-muted">
      {navItems.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                isActive
                  ? "bg-sidebar-accent/15 text-sidebar-accent-foreground"
                  : "text-sidebar-muted hover:bg-sidebar-accent/10 hover:text-sidebar-foreground"
              )
            }
            onClick={onNavigate}
          >
            <Icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );
};

export default Sidebar;
export { navItems };
