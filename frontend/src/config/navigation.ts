import {
  CircleDot,
  Download,
  LucideIcon,
  Music,
  Radio,
  Settings,
  Sparkles,
  Users
} from 'lucide-react';

export interface NavigationItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export const navigationItems: NavigationItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: CircleDot },
  { to: '/downloads', label: 'Downloads', icon: Download },
  { to: '/artists', label: 'Artists', icon: Users },
  { to: '/spotify', label: 'Spotify', icon: Music },
  { to: '/soulseek', label: 'Soulseek', icon: Radio },
  { to: '/matching', label: 'Matching', icon: Sparkles },
  { to: '/settings', label: 'Settings', icon: Settings }
];
